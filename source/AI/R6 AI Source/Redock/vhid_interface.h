#pragma once

#include <Windows.h>

//
// IOCTL definitions for user-mode communication
// (mirrors mouse-movement-driver src/shared/vhid_interface.h)
//
#define VHID_MOUSE_DEVICE_TYPE 0x8000

#define IOCTL_VHID_MOUSE_MOVE \
    CTL_CODE(VHID_MOUSE_DEVICE_TYPE, 0x801, METHOD_BUFFERED, FILE_ANY_ACCESS)

#define IOCTL_VHID_SECURE_INPUT \
    CTL_CODE(VHID_MOUSE_DEVICE_TYPE, 0x802, METHOD_BUFFERED, FILE_ANY_ACCESS)

typedef struct _MOUSE_MOVE_REQUEST {
    long dx;
    long dy;
    unsigned char buttons;  // Bitmask: 1=Left, 2=Right, 4=Middle, 8=X1, 16=X2
    unsigned char wheel;
} MOUSE_MOVE_REQUEST, *PMOUSE_MOVE_REQUEST;

#define VHID_ENCRYPTION_KEY 0xAB

typedef enum _VHID_PACKET_TYPE {
    PacketType_Mouse = 1,
    PacketType_Keyboard = 2
} VHID_PACKET_TYPE;

typedef struct _VHID_SECURE_PACKET {
    unsigned char Type;
    unsigned char Size;
    unsigned char Payload[16];
} VHID_SECURE_PACKET, *PVHID_SECURE_PACKET;

typedef struct _KEYBOARD_INPUT_REQUEST {
    unsigned short MakeCode;
    unsigned short Flags;
    unsigned short Reserved;
} KEYBOARD_INPUT_REQUEST, *PKEYBOARD_INPUT_REQUEST;

typedef struct _HID_KEYBOARD_REPORT {
    unsigned char ReportId;
    unsigned char Modifiers;
    unsigned char Reserved;
    unsigned char Keys[6];
} HID_KEYBOARD_REPORT, *PHID_KEYBOARD_REPORT;

typedef struct _HID_MOUSE_REPORT {
    unsigned char ReportId;
    unsigned char Buttons;
    char X;
    char Y;
    char Wheel;
} HID_MOUSE_REPORT, *PHID_MOUSE_REPORT;
