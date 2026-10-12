#include <hidboot.h>
#include <usbhub.h>
#include <HID-Project.h>
#include <hiduniversal.h>
#include <Wire.h>
#include <SPI.h>
#include <stdlib.h>
#include <string.h>

#define RPT_LEN  8
#define BUFFER_SIZE 32  // Buffer for serial input parsing

USB Usb;
USBHub Hub(&Usb);
HIDUniversal Hid(&Usb);

class HIDMouseEvents {
  public:
    void OnButtonDn(uint8_t but_id) {
      if (but_id == 0x08) {
          Mouse.press(MOUSE_PREV);
      } else if (but_id == 0x10) {
          Mouse.press(MOUSE_NEXT);
      } else {
          Mouse.press(but_id);
      }
  }
  void OnButtonUp(uint8_t but_id) {
      if (but_id == 0x08) {
          Mouse.release(MOUSE_PREV);
      } else if (but_id == 0x10) {
          Mouse.release(MOUSE_NEXT);
      } else {
          Mouse.release(but_id);
      }
    }
    void Move(int8_t xm, int8_t ym, int8_t scr) {
        Mouse.move(xm, ym, scr);
    }
};

class HIDMouseReportParser : public HIDReportParser {
    HIDMouseEvents *mouEvents;
    uint8_t oldButtons;
  public:
    HIDMouseReportParser(HIDMouseEvents *evt) : mouEvents(evt), oldButtons(0) {}
    
    void Parse(USBHID *hid, bool is_rpt_id, uint8_t len, uint8_t *buf) {
        uint8_t buttons = buf[0]; // For mouse clicks
        if (buttons != oldButtons) {
            for (uint8_t but_id = 1; but_id <= 16; but_id <<= 1) {
                if (buttons & but_id) {
                    if (!(oldButtons & but_id)) mouEvents->OnButtonDn(but_id);
                } else {
                    if (oldButtons & but_id) mouEvents->OnButtonUp(but_id);
                }
            }
            oldButtons = buttons;
        }
        int8_t xm = buf[2], ym = buf[4], scr = buf[6]; // For mouse movements and scroll wheel
        if (xm || ym || scr) mouEvents->Move(xm, ym, scr);
    }
};

HIDMouseEvents MouEvents;
HIDMouseReportParser Mou(&MouEvents);
HIDBoot<USB_HID_PROTOCOL_MOUSE> HidMouse(&Usb);

char received_code[BUFFER_SIZE];  // Fixed-size buffer for input
uint8_t index1 = 0;

// Low-latency serial link.
//
// The host sends an 8-byte packet per movement step; at the old 9600 baud that
// packet occupied the wire for ~8ms before the next one could even start, which
// is a hard floor on input latency and reaction time. 115200 baud cuts that to
// under 1ms while keeping the packet format byte-for-byte identical, so no host
// change other than the baud rate is required. The ATmega32u4 USB-serial bridge
// on the Leonardo handles this rate reliably.
#define SERIAL_BAUD 115200

void setup() {
    Mouse.begin();
    Serial.begin(SERIAL_BAUD);
    // A 1ms read timeout keeps loop() from ever blocking on a partial packet;
    // a complete packet is always terminated by the '*' sentinel.
    Serial.setTimeout(1);
    Usb.Init();
    if (!Hid.SetReportParser(0, &Mou)) {
    }
}

void loop() {
    Usb.Task();  // Handle USB events

    // Drain everything that is already buffered before returning to USB, so a
    // burst of steps is applied in order in a single pass instead of one step
    // per loop() iteration. This is the reaction-time win: the queue is emptied
    // as fast as the bytes arrive.
    while (Serial.available()) {
        char c = Serial.read();
        if (c == '*') {
            received_code[index1] = '\0';  // Null-terminate the string

            // Hand-rolled integer parse: strtok/atoi allocate nothing but scan
            // the string three times; parsing fields in one pass is quicker and
            // leaves the buffer reusable immediately.
            int values[3] = {0, 0, 0};
            int field = 0;
            int sign = 1;
            int digit = 0;
            bool have_digit = false;
            for (uint8_t i = 0; i <= index1 && field < 3; ++i) {
                char ch = received_code[i];
                if (ch == '-' && !have_digit) {
                    sign = -1;
                } else if (ch >= '0' && ch <= '9') {
                    digit = digit * 10 + (ch - '0');
                    have_digit = true;
                } else {
                    if (have_digit) {
                        values[field++] = sign * digit;
                        digit = 0;
                        sign = 1;
                        have_digit = false;
                    }
                    if (ch == ',' || ch == '\0') {
                        // Advance to the next field on the separator or the end.
                        continue;
                    }
                }
            }
            if (have_digit && field < 3) {
                values[field++] = sign * digit;
            }

            if (field >= 2 && (values[0] != 0 || values[1] != 0)) {
                Mouse.move(values[0], values[1], 0);
            }
            if (field >= 3 && values[2] != 0) {
                Mouse.click();
            }
            index1 = 0;  // Reset index for next input
        } 
        else if (index1 < BUFFER_SIZE - 1) {  // Prevent buffer overflow
            received_code[index1++] = c;
        }
    }
}
