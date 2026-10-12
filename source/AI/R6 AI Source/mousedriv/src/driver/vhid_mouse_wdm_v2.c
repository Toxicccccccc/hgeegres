#include <ntddk.h>
#include <ntddmou.h>
#include <ntstrsafe.h>

//
// Pure WDM Virtual Mouse Driver - Mapper Compatible
// Uses direct mouclass callback injection for real mouse input
// FULLY RELOCATABLE - No global strings or static data dependencies
//

#pragma warning(disable: 4201)

// ============================================================================
// Configuration
// ============================================================================

#define VHID_DEVICE_TYPE        0x8000
#define VHID_POOL_TAG           'dihV'

#define IOCTL_VHID_MOUSE_MOVE \
    CTL_CODE(VHID_DEVICE_TYPE, 0x801, METHOD_BUFFERED, FILE_ANY_ACCESS)

#define IOCTL_VHID_SECURE_INPUT \
    CTL_CODE(VHID_DEVICE_TYPE, 0x802, METHOD_BUFFERED, FILE_ANY_ACCESS)

#define VHID_ENCRYPTION_KEY     0xAB

// ============================================================================
// Structures
// ============================================================================

typedef struct _MOUSE_MOVE_REQUEST {
    LONG dx;
    LONG dy;
    UCHAR buttons;
    UCHAR wheel;
} MOUSE_MOVE_REQUEST, *PMOUSE_MOVE_REQUEST;

typedef enum _VHID_PACKET_TYPE {
    PacketType_Mouse = 1,
    PacketType_Keyboard = 2
} VHID_PACKET_TYPE;

typedef struct _VHID_SECURE_PACKET {
    UCHAR Type;
    UCHAR Size;
    UCHAR Payload[16];
} VHID_SECURE_PACKET, *PVHID_SECURE_PACKET;

// Mouse class callback signature
typedef VOID (*MOUSE_SERVICE_CALLBACK)(
    PDEVICE_OBJECT DeviceObject,
    PMOUSE_INPUT_DATA InputDataStart,
    PMOUSE_INPUT_DATA InputDataEnd,
    PULONG InputDataConsumed
);

// Mouse class device extension structure (partial, from reverse engineering)
typedef struct _MOUSE_CLASS_DATA {
    ULONG Reserved1;
    PDEVICE_OBJECT Self;
    ULONG Reserved2[10];
    MOUSE_SERVICE_CALLBACK ServiceCallback;
    // ... more fields we don't need
} MOUSE_CLASS_DATA, *PMOUSE_CLASS_DATA;

// Our device extension - ALL STATE STORED HERE (no globals!)
typedef struct _VHID_EXTENSION {
    PDEVICE_OBJECT Self;
    PDEVICE_OBJECT MouseDevice;
    MOUSE_SERVICE_CALLBACK MouseCallback;
    KSPIN_LOCK Lock;
    UCHAR LastButtons;
    
    // Store device name strings in extension (relocatable)
    WCHAR DeviceNameBuffer[64];
    WCHAR SymbolicLinkBuffer[64];
    UNICODE_STRING DeviceName;
    UNICODE_STRING SymbolicLink;
    BOOLEAN SymbolicLinkCreated;
} VHID_EXTENSION, *PVHID_EXTENSION;

// ============================================================================
// Globals - Minimized for mapper compatibility
// Only a single pointer that gets set during DriverEntry
// ============================================================================

static PDEVICE_OBJECT g_Device = NULL;

// ============================================================================
// Runtime import resolution (kdmapper often breaks PE data imports / IAT)
// ============================================================================

typedef NTSTATUS (NTAPI *FN_IoCreateDriver)(
    PUNICODE_STRING DriverName,
    PDRIVER_INITIALIZE InitializationFunction
);

static FN_IoCreateDriver DynIoCreateDriver = NULL;

static FN_IoCreateDriver ResolveIoCreateDriver(VOID)
{
    UNICODE_STRING name;

    if (DynIoCreateDriver != NULL) {
        return DynIoCreateDriver;
    }

    RtlInitUnicodeString(&name, L"IoCreateDriver");
    DynIoCreateDriver = (FN_IoCreateDriver)MmGetSystemRoutineAddress(&name);
    return DynIoCreateDriver;
}

NTKERNELAPI PDEVICE_OBJECT IoGetLowerDeviceObject(PDEVICE_OBJECT DeviceObject);
NTKERNELAPI PDEVICE_OBJECT IoGetAttachedDeviceReference(PDEVICE_OBJECT DeviceObject);

NTKERNELAPI NTSTATUS ObReferenceObjectByName(
    PUNICODE_STRING ObjectName,
    ULONG Attributes,
    PVOID AccessState,
    ACCESS_MASK DesiredAccess,
    POBJECT_TYPE ObjectType,
    KPROCESSOR_MODE AccessMode,
    PVOID ParseContext,
    PVOID* Object
);

typedef NTSTATUS (NTAPI *FN_ZwQuerySystemInformation)(
    ULONG SystemInformationClass,
    PVOID SystemInformation,
    ULONG SystemInformationLength,
    PULONG ReturnLength
);

#ifndef SystemModuleInformation
#define SystemModuleInformation 11
#endif

typedef struct _RTL_PROCESS_MODULE_INFORMATION_V2 {
    HANDLE Section;
    PVOID MappedBase;
    PVOID ImageBase;
    ULONG ImageSize;
    ULONG Flags;
    USHORT LoadOrderIndex;
    USHORT InitOrderIndex;
    USHORT LoadCount;
    USHORT OffsetToFileName;
    UCHAR FullPathName[256];
} RTL_PROCESS_MODULE_INFORMATION_V2, *PRTL_PROCESS_MODULE_INFORMATION_V2;

typedef struct _RTL_PROCESS_MODULES_V2 {
    ULONG NumberOfModules;
    RTL_PROCESS_MODULE_INFORMATION_V2 Modules[1];
} RTL_PROCESS_MODULES_V2, *PRTL_PROCESS_MODULES_V2;

#define IO_TYPE_DEVICE 3

static BOOLEAN IsKernelPtr(ULONG_PTR Value)
{
    return (Value >= 0xFFFF800000000000ULL && Value < 0xFFFFFFFFFFFFF000ULL);
}

static BOOLEAN SafeReadUlongPtr(PVOID Address, PULONG_PTR OutValue)
{
    __try {
        *OutValue = *(PULONG_PTR)Address;
    }
    __except (EXCEPTION_EXECUTE_HANDLER) {
        return FALSE;
    }

    return TRUE;
}

static BOOLEAN NameIsMouClassSys(PCSTR Name)
{
    static const char target[] = { 'm','o','u','c','l','a','s','s','.','s','y','s', '\0' };
    SIZE_T i;
    SIZE_T nameLen;
    SIZE_T targetLen = sizeof(target) - 1;

    if (Name == NULL) {
        return FALSE;
    }

    nameLen = 0;
    while (Name[nameLen] != '\0' && nameLen < 64) {
        nameLen++;
    }
    if (nameLen < targetLen) {
        return FALSE;
    }

    for (i = 0; i < targetLen; i++) {
        char a = Name[nameLen - targetLen + i];
        char b = target[i];
        if (a >= 'A' && a <= 'Z') {
            a = (char)(a - 'A' + 'a');
        }
        if (b >= 'A' && b <= 'Z') {
            b = (char)(b - 'A' + 'a');
        }
        if (a != b) {
            return FALSE;
        }
    }

    return TRUE;
}

static NTSTATUS GetMouClassImageRange(PVOID* ImageBase, PULONG ImageSize)
{
    FN_ZwQuerySystemInformation querySystemInfo = NULL;
    UNICODE_STRING routineName;
    PVOID buffer = NULL;
    ULONG bufferSize = 0x8000;
    ULONG returnLength = 0;
    NTSTATUS status;
    PRTL_PROCESS_MODULES_V2 modules;
    ULONG i;

    *ImageBase = NULL;
    *ImageSize = 0;

    RtlInitUnicodeString(&routineName, L"ZwQuerySystemInformation");
    querySystemInfo = (FN_ZwQuerySystemInformation)MmGetSystemRoutineAddress(&routineName);
    if (querySystemInfo == NULL) {
        return STATUS_PROCEDURE_NOT_FOUND;
    }

    for (;;) {
        buffer = ExAllocatePoolWithTag(NonPagedPool, bufferSize, VHID_POOL_TAG);
        if (buffer == NULL) {
            return STATUS_INSUFFICIENT_RESOURCES;
        }

        status = querySystemInfo(SystemModuleInformation, buffer, bufferSize, &returnLength);
        if (status == STATUS_INFO_LENGTH_MISMATCH) {
            ExFreePoolWithTag(buffer, VHID_POOL_TAG);
            buffer = NULL;
            bufferSize = returnLength + 0x1000;
            continue;
        }
        if (!NT_SUCCESS(status)) {
            ExFreePoolWithTag(buffer, VHID_POOL_TAG);
            return status;
        }
        break;
    }

    modules = (PRTL_PROCESS_MODULES_V2)buffer;
    status = STATUS_NOT_FOUND;

    for (i = 0; i < modules->NumberOfModules; i++) {
        PRTL_PROCESS_MODULE_INFORMATION_V2 mod = &modules->Modules[i];
        PCSTR fileName = (PCSTR)(mod->FullPathName + mod->OffsetToFileName);

        if (NameIsMouClassSys(fileName)) {
            *ImageBase = mod->ImageBase;
            *ImageSize = mod->ImageSize;
            status = STATUS_SUCCESS;
            break;
        }
    }

    ExFreePoolWithTag(buffer, VHID_POOL_TAG);
    return status;
}

static BOOLEAN IsPointerInMouClassImage(
    PVOID Pointer,
    PVOID MouClassBase,
    ULONG MouClassSize
)
{
    ULONG_PTR addr = (ULONG_PTR)Pointer;
    ULONG_PTR base = (ULONG_PTR)MouClassBase;

    if (MouClassBase == NULL || MouClassSize == 0) {
        return FALSE;
    }

    return (addr >= base && addr < base + MouClassSize);
}

static BOOLEAN IsDeviceObjectPointer(PVOID Candidate)
{
    PDEVICE_OBJECT deviceObject;

    if (!IsKernelPtr((ULONG_PTR)Candidate)) {
        return FALSE;
    }

    deviceObject = (PDEVICE_OBJECT)Candidate;
    __try {
        if (deviceObject->Type != IO_TYPE_DEVICE) {
            return FALSE;
        }
        if (deviceObject->Size < sizeof(DEVICE_OBJECT)) {
            return FALSE;
        }
    }
    __except (EXCEPTION_EXECUTE_HANDLER) {
        return FALSE;
    }

    return TRUE;
}

static POBJECT_TYPE ResolveDriverObjectType(VOID)
{
    UNICODE_STRING routineName;
    POBJECT_TYPE** objectTypePointer = NULL;

    RtlInitUnicodeString(&routineName, L"IoDriverObjectType");
    objectTypePointer = (POBJECT_TYPE**)MmGetSystemRoutineAddress(&routineName);
    if (objectTypePointer == NULL || *objectTypePointer == NULL) {
        return NULL;
    }

    return *objectTypePointer;
}

static BOOLEAN IsPointerInDriverImage(
    PVOID Pointer,
    PVOID DriverStart,
    ULONG DriverSize
)
{
    ULONG_PTR addr = (ULONG_PTR)Pointer;
    ULONG_PTR base = (ULONG_PTR)DriverStart;

    if (DriverStart == NULL || DriverSize == 0) {
        return FALSE;
    }

    return (addr >= base && addr < base + DriverSize);
}

static NTSTATUS ReferenceDriverObject(
    POBJECT_TYPE ObjectType,
    PCWSTR DriverName,
    PDRIVER_OBJECT* OutDriver
)
{
    UNICODE_STRING name;
    RtlInitUnicodeString(&name, DriverName);
    return ObReferenceObjectByName(
        &name,
        OBJ_CASE_INSENSITIVE,
        NULL,
        0,
        ObjectType,
        KernelMode,
        NULL,
        (PVOID*)OutDriver
    );
}

/*
 * Win10/11 (incl. 22H2): MouHID port extension holds CONNECT_DATA
 * (MouClass device object + MouseClassServiceCallback). Match any MouClass
 * device in the pair, not only a specific NextDevice instance.
 */
static NTSTATUS ScanPortDeviceForConnectData(
    PDEVICE_OBJECT PortDevice,
    PDRIVER_OBJECT ClassDriver,
    PVHID_EXTENSION Ext
)
{
    PULONG_PTR deviceExtension;
    ULONG_PTR extensionSlots;
    ULONG_PTR index;
    PVOID classDriverStart;
    ULONG classDriverSize;
    PDEVICE_OBJECT classDeviceObject;

    if (PortDevice == NULL || PortDevice->DeviceExtension == NULL) {
        return STATUS_NOT_FOUND;
    }

    if (PortDevice->DeviceObjectExtension != NULL &&
        PortDevice->DeviceObjectExtension > PortDevice->DeviceExtension) {
        extensionSlots =
            ((ULONG_PTR)PortDevice->DeviceObjectExtension -
             (ULONG_PTR)PortDevice->DeviceExtension) / sizeof(ULONG_PTR);
    } else {
        extensionSlots = 0x180;
    }

    if (extensionSlots > 0x200) {
        extensionSlots = 0x200;
    }

    classDriverStart = ClassDriver->DriverStart;
    classDriverSize = ClassDriver->DriverSize;
    deviceExtension = (PULONG_PTR)PortDevice->DeviceExtension;

    for (index = 0; index + 1 < extensionSlots; index++) {
        ULONG_PTR classDevicePtr = 0;
        ULONG_PTR callbackPtr = 0;

        if (!SafeReadUlongPtr(&deviceExtension[index], &classDevicePtr)) {
            continue;
        }
        if (!SafeReadUlongPtr(&deviceExtension[index + 1], &callbackPtr)) {
            continue;
        }

        if (!IsDeviceObjectPointer((PVOID)classDevicePtr)) {
            continue;
        }

        classDeviceObject = (PDEVICE_OBJECT)classDevicePtr;
        if (classDeviceObject->DriverObject != ClassDriver) {
            continue;
        }

        if (!IsPointerInDriverImage(
                (PVOID)callbackPtr,
                classDriverStart,
                classDriverSize) &&
            !(callbackPtr > (ULONG_PTR)ClassDriver && IsKernelPtr(callbackPtr))) {
            continue;
        }

        ObReferenceObject(classDeviceObject);
        Ext->MouseDevice = classDeviceObject;
        Ext->MouseCallback = (MOUSE_SERVICE_CALLBACK)callbackPtr;
        return STATUS_SUCCESS;
    }

    return STATUS_NOT_FOUND;
}

static NTSTATUS ScanHidPortDriver(
    PDRIVER_OBJECT ClassDriver,
    PDRIVER_OBJECT PortDriver,
    PVHID_EXTENSION Ext
)
{
    PDEVICE_OBJECT portDevice;
    PDEVICE_OBJECT attached;
    NTSTATUS status;

    status = STATUS_NOT_FOUND;

    for (portDevice = PortDriver->DeviceObject;
         portDevice != NULL && !NT_SUCCESS(status);
         portDevice = portDevice->NextDevice) {
        status = ScanPortDeviceForConnectData(portDevice, ClassDriver, Ext);
        if (NT_SUCCESS(status)) {
            break;
        }

        for (attached = portDevice->AttachedDevice;
             attached != NULL && !NT_SUCCESS(status);
             attached = attached->AttachedDevice) {
            status = ScanPortDeviceForConnectData(attached, ClassDriver, Ext);
        }
    }

    return status;
}

static NTSTATUS FindMouseCallbackViaPortDrivers(
    PVHID_EXTENSION Ext,
    PDRIVER_OBJECT ClassDriver,
    POBJECT_TYPE ObjectType
)
{
    static const PCWSTR portDriverNames[] = {
        L"\\Driver\\MouHID",   /* USB / BT mice on Win11 22H2 */
        L"\\Driver\\HidUsb",   /* HID over USB */
        L"\\Driver\\i8042prt", /* PS/2 trackpad / keyboard port */
    };
    ULONG i;
    NTSTATUS status;
    PDRIVER_OBJECT portDriver = NULL;

    for (i = 0; i < sizeof(portDriverNames) / sizeof(portDriverNames[0]); i++) {
        status = ReferenceDriverObject(ObjectType, portDriverNames[i], &portDriver);
        if (!NT_SUCCESS(status)) {
            continue;
        }

        status = ScanHidPortDriver(ClassDriver, portDriver, Ext);
        ObDereferenceObject(portDriver);
        portDriver = NULL;

        if (NT_SUCCESS(status)) {
            return STATUS_SUCCESS;
        }
    }

    return STATUS_NOT_FOUND;
}

static NTSTATUS FindMouseCallbackViaMouHid(PVHID_EXTENSION Ext)
{
    POBJECT_TYPE driverObjectType;
    PDRIVER_OBJECT classDriver = NULL;
    NTSTATUS status;
    WCHAR classBuf[32];
    WCHAR* p;

    if (Ext->MouseCallback != NULL) {
        return STATUS_SUCCESS;
    }

    driverObjectType = ResolveDriverObjectType();
    if (driverObjectType == NULL) {
        return STATUS_NOT_FOUND;
    }

    p = classBuf;
    *p++ = L'\\'; *p++ = L'D'; *p++ = L'r'; *p++ = L'i'; *p++ = L'v';
    *p++ = L'e'; *p++ = L'r'; *p++ = L'\\'; *p++ = L'M'; *p++ = L'o';
    *p++ = L'u'; *p++ = L'C'; *p++ = L'l'; *p++ = L'a'; *p++ = L's'; *p++ = L's';
    *p = L'\0';

    status = ReferenceDriverObject(
        driverObjectType,
        classBuf,
        &classDriver
    );
    if (!NT_SUCCESS(status)) {
        return status;
    }

    status = FindMouseCallbackViaPortDrivers(Ext, classDriver, driverObjectType);

    if (!NT_SUCCESS(status)) {
        PDEVICE_OBJECT target = classDriver->DeviceObject;
        while (target != NULL) {
            if (target->NextDevice == NULL) {
                break;
            }
            target = target->NextDevice;
        }
        if (target != NULL) {
            status = ScanPortDeviceForConnectData(target, classDriver, Ext);
        }
    }

    ObDereferenceObject(classDriver);
    return status;
}

// ============================================================================
// Function Declarations
// ============================================================================

DRIVER_INITIALIZE DriverEntry;
DRIVER_INITIALIZE VhidDriverInitialize;
DRIVER_UNLOAD DriverUnload;

_Dispatch_type_(IRP_MJ_CREATE)
_Dispatch_type_(IRP_MJ_CLOSE)
DRIVER_DISPATCH VhidCreateClose;

_Dispatch_type_(IRP_MJ_DEVICE_CONTROL)
DRIVER_DISPATCH VhidDeviceControl;

// ============================================================================
// Mouse Injection via MouClass Callback
// ============================================================================

static NTSTATUS TryFindCallbackOnDevice(
    PDEVICE_OBJECT DeviceObject,
    PVHID_EXTENSION Ext,
    PVOID MouClassBase,
    ULONG MouClassSize
)
{
    PVOID devExt;
    ULONG offset;
    ULONG_PTR classDevice = 0;
    ULONG_PTR classService = 0;

    if (DeviceObject == NULL || MouClassBase == NULL || MouClassSize == 0) {
        return STATUS_NOT_FOUND;
    }

    devExt = DeviceObject->DeviceExtension;
    if (devExt == NULL) {
        return STATUS_NOT_FOUND;
    }

    // Scan for CONNECT_DATA (ClassDeviceObject + ClassService) in the device extension.
    for (offset = 0; offset <= 0x200; offset += sizeof(ULONG_PTR)) {
        if (!SafeReadUlongPtr((PUCHAR)devExt + offset, &classDevice)) {
            continue;
        }
        if (!SafeReadUlongPtr((PUCHAR)devExt + offset + sizeof(ULONG_PTR), &classService)) {
            continue;
        }

        if (!IsPointerInMouClassImage((PVOID)classService, MouClassBase, MouClassSize)) {
            continue;
        }
        if (!IsDeviceObjectPointer((PVOID)classDevice)) {
            continue;
        }

        ObReferenceObject((PDEVICE_OBJECT)classDevice);
        Ext->MouseDevice = (PDEVICE_OBJECT)classDevice;
        Ext->MouseCallback = (MOUSE_SERVICE_CALLBACK)classService;
        return STATUS_SUCCESS;
    }

    return STATUS_NOT_FOUND;
}

static VOID ScanDeviceStackForCallback(
    PDEVICE_OBJECT StartDevice,
    PVHID_EXTENSION Ext,
    PVOID MouClassBase,
    ULONG MouClassSize,
    PNTSTATUS OutStatus
)
{
    PDEVICE_OBJECT walkDevice = NULL;
    PDEVICE_OBJECT lowerDevice = NULL;
    PDEVICE_OBJECT topDevice = NULL;
    PDEVICE_OBJECT attached = NULL;

    if (StartDevice == NULL || OutStatus == NULL) {
        return;
    }

    if (NT_SUCCESS(*OutStatus)) {
        return;
    }

    walkDevice = StartDevice;
    while (walkDevice != NULL) {
        if (NT_SUCCESS(TryFindCallbackOnDevice(walkDevice, Ext, MouClassBase, MouClassSize))) {
            *OutStatus = STATUS_SUCCESS;
            if (walkDevice != StartDevice) {
                ObDereferenceObject(walkDevice);
            }
            break;
        }

        lowerDevice = IoGetLowerDeviceObject(walkDevice);
        if (walkDevice != StartDevice) {
            ObDereferenceObject(walkDevice);
        }
        walkDevice = lowerDevice;
    }

    if (NT_SUCCESS(*OutStatus)) {
        return;
    }

    topDevice = IoGetAttachedDeviceReference(StartDevice);
    attached = topDevice;
    while (attached != NULL) {
        if (NT_SUCCESS(TryFindCallbackOnDevice(attached, Ext, MouClassBase, MouClassSize))) {
            *OutStatus = STATUS_SUCCESS;
            break;
        }
        attached = attached->AttachedDevice;
    }
    ObDereferenceObject(topDevice);
}

static VOID BuildPointerClassDeviceName(WCHAR* Buffer, ULONG Index, PUSHORT NameLength)
{
    WCHAR* p = Buffer;

    *p++ = L'\\';
    *p++ = L'D';
    *p++ = L'e';
    *p++ = L'v';
    *p++ = L'i';
    *p++ = L'c';
    *p++ = L'e';
    *p++ = L'\\';
    *p++ = L'P';
    *p++ = L'o';
    *p++ = L'i';
    *p++ = L'n';
    *p++ = L't';
    *p++ = L'e';
    *p++ = L'r';
    *p++ = L'C';
    *p++ = L'l';
    *p++ = L'a';
    *p++ = L's';
    *p++ = L's';
    *p++ = (WCHAR)(L'0' + Index);
    *p = L'\0';

    *NameLength = (USHORT)((p - Buffer) * sizeof(WCHAR));
}

static NTSTATUS FindMouseCallbackViaMouClassDriver(
    PVHID_EXTENSION Ext,
    PVOID MouClassBase,
    ULONG MouClassSize
)
{
    UNICODE_STRING driverName;
    POBJECT_TYPE driverObjectType = NULL;
    PDRIVER_OBJECT mouDriver = NULL;
    PDEVICE_OBJECT deviceObject = NULL;
    NTSTATUS status;
    WCHAR driverNameBuf[32];
    WCHAR* p;

    driverObjectType = ResolveDriverObjectType();
    if (driverObjectType == NULL) {
        return STATUS_NOT_FOUND;
    }

    p = driverNameBuf;
    *p++ = L'\\';
    *p++ = L'D';
    *p++ = L'r';
    *p++ = L'i';
    *p++ = L'v';
    *p++ = L'e';
    *p++ = L'r';
    *p++ = L'\\';
    *p++ = L'M';
    *p++ = L'o';
    *p++ = L'u';
    *p++ = L'C';
    *p++ = L'l';
    *p++ = L'a';
    *p++ = L's';
    *p++ = L's';
    *p = L'\0';

    driverName.Buffer = driverNameBuf;
    driverName.Length = 17 * sizeof(WCHAR);
    driverName.MaximumLength = sizeof(driverNameBuf);

    status = ObReferenceObjectByName(
        &driverName,
        OBJ_CASE_INSENSITIVE,
        NULL,
        0,
        driverObjectType,
        KernelMode,
        NULL,
        (PVOID*)&mouDriver
    );

    if (!NT_SUCCESS(status)) {
        return status;
    }

    status = STATUS_NOT_FOUND;
    for (deviceObject = mouDriver->DeviceObject; deviceObject != NULL; deviceObject = deviceObject->NextDevice) {
        ScanDeviceStackForCallback(deviceObject, Ext, MouClassBase, MouClassSize, &status);
        if (NT_SUCCESS(status)) {
            break;
        }
    }

    ObDereferenceObject(mouDriver);
    return status;
}

static NTSTATUS FindMouseCallback(PVHID_EXTENSION Ext)
{
    NTSTATUS status;
    UNICODE_STRING deviceName;
    PFILE_OBJECT fileObject = NULL;
    PDEVICE_OBJECT deviceObject = NULL;
    PVOID mouClassBase = NULL;
    ULONG mouClassSize = 0;
    WCHAR deviceNameBuf[32];
    USHORT deviceNameLength = 0;
    ULONG pointerIndex;

    if (Ext->MouseCallback != NULL) {
        return STATUS_SUCCESS;
    }

    status = FindMouseCallbackViaMouHid(Ext);
    if (NT_SUCCESS(status)) {
        return STATUS_SUCCESS;
    }

    status = GetMouClassImageRange(&mouClassBase, &mouClassSize);
    if (!NT_SUCCESS(status)) {
        mouClassBase = NULL;
        mouClassSize = 0;
    }

    status = STATUS_NOT_FOUND;

    /* Win11 22H2: try PointerClass0-9 (multi-mouse / split stacks) */
    for (pointerIndex = 0; pointerIndex < 10; pointerIndex++) {
        BuildPointerClassDeviceName(deviceNameBuf, pointerIndex, &deviceNameLength);

        deviceName.Buffer = deviceNameBuf;
        deviceName.Length = deviceNameLength;
        deviceName.MaximumLength = sizeof(deviceNameBuf);

        fileObject = NULL;
        deviceObject = NULL;

        if (!NT_SUCCESS(IoGetDeviceObjectPointer(
                &deviceName,
                FILE_READ_DATA,
                &fileObject,
                &deviceObject))) {
            continue;
        }

        if (mouClassBase != NULL) {
            ScanDeviceStackForCallback(deviceObject, Ext, mouClassBase, mouClassSize, &status);
        }

        ObDereferenceObject(fileObject);
        fileObject = NULL;

        if (NT_SUCCESS(status)) {
            return STATUS_SUCCESS;
        }
    }

    if (!NT_SUCCESS(status) && mouClassBase != NULL) {
        status = FindMouseCallbackViaMouClassDriver(Ext, mouClassBase, mouClassSize);
    }

    return status;
}

static NTSTATUS InjectMouse(PVHID_EXTENSION Ext, PMOUSE_MOVE_REQUEST Move)
{
    MOUSE_INPUT_DATA inputData = {0};
    ULONG consumed = 0;
    KIRQL irql;
    KIRQL oldIrql;
    
    if (Ext->MouseCallback == NULL || Ext->MouseDevice == NULL) {
        return STATUS_DEVICE_NOT_READY;
    }
    
    // Build mouse input data
    inputData.UnitId = 0;
    inputData.Flags = MOUSE_MOVE_RELATIVE;
    inputData.LastX = Move->dx;
    inputData.LastY = Move->dy;
    
    // Handle button state changes
    KeAcquireSpinLock(&Ext->Lock, &irql);
    
    // Left button
    if ((Move->buttons & 0x01) && !(Ext->LastButtons & 0x01)) {
        inputData.ButtonFlags |= MOUSE_LEFT_BUTTON_DOWN;
    } else if (!(Move->buttons & 0x01) && (Ext->LastButtons & 0x01)) {
        inputData.ButtonFlags |= MOUSE_LEFT_BUTTON_UP;
    }
    
    // Right button
    if ((Move->buttons & 0x02) && !(Ext->LastButtons & 0x02)) {
        inputData.ButtonFlags |= MOUSE_RIGHT_BUTTON_DOWN;
    } else if (!(Move->buttons & 0x02) && (Ext->LastButtons & 0x02)) {
        inputData.ButtonFlags |= MOUSE_RIGHT_BUTTON_UP;
    }
    
    // Middle button
    if ((Move->buttons & 0x04) && !(Ext->LastButtons & 0x04)) {
        inputData.ButtonFlags |= MOUSE_MIDDLE_BUTTON_DOWN;
    } else if (!(Move->buttons & 0x04) && (Ext->LastButtons & 0x04)) {
        inputData.ButtonFlags |= MOUSE_MIDDLE_BUTTON_UP;
    }
    
    // X1 button
    if ((Move->buttons & 0x08) && !(Ext->LastButtons & 0x08)) {
        inputData.ButtonFlags |= MOUSE_BUTTON_4_DOWN;
    } else if (!(Move->buttons & 0x08) && (Ext->LastButtons & 0x08)) {
        inputData.ButtonFlags |= MOUSE_BUTTON_4_UP;
    }
    
    // X2 button
    if ((Move->buttons & 0x10) && !(Ext->LastButtons & 0x10)) {
        inputData.ButtonFlags |= MOUSE_BUTTON_5_DOWN;
    } else if (!(Move->buttons & 0x10) && (Ext->LastButtons & 0x10)) {
        inputData.ButtonFlags |= MOUSE_BUTTON_5_UP;
    }
    
    Ext->LastButtons = Move->buttons;
    KeReleaseSpinLock(&Ext->Lock, irql);
    
    // Wheel
    if (Move->wheel != 0) {
        inputData.ButtonFlags |= MOUSE_WHEEL;
        inputData.ButtonData = (SHORT)((CHAR)Move->wheel) * 120;
    }
    
    // MouseClassServiceCallback must run at DISPATCH_LEVEL
    KeRaiseIrql(DISPATCH_LEVEL, &oldIrql);
    __try {
        Ext->MouseCallback(
            Ext->MouseDevice,
            &inputData,
            &inputData + 1,
            &consumed
        );
    }
    __except (EXCEPTION_EXECUTE_HANDLER) {
        KeLowerIrql(oldIrql);
        return STATUS_UNSUCCESSFUL;
    }
    KeLowerIrql(oldIrql);
    
    return STATUS_SUCCESS;
}

// ============================================================================
// Helper: Build device name strings dynamically (relocatable)
// ============================================================================

static VOID BuildDeviceStrings(PVHID_EXTENSION Ext)
{
    // Build device name: \Device\VHIDMouse
    // Using character-by-character assignment to avoid string literal relocation issues
    WCHAR* p = Ext->DeviceNameBuffer;
    *p++ = L'\\'; *p++ = L'D'; *p++ = L'e'; *p++ = L'v'; *p++ = L'i'; 
    *p++ = L'c'; *p++ = L'e'; *p++ = L'\\'; *p++ = L'V'; *p++ = L'H'; 
    *p++ = L'I'; *p++ = L'D'; *p++ = L'M'; *p++ = L'o'; *p++ = L'u'; 
    *p++ = L's'; *p++ = L'e'; *p = L'\0';
    
    Ext->DeviceName.Buffer = Ext->DeviceNameBuffer;
    Ext->DeviceName.Length = 17 * sizeof(WCHAR);
    Ext->DeviceName.MaximumLength = sizeof(Ext->DeviceNameBuffer);
    
    // Build symbolic link: \DosDevices\VHIDMouse
    p = Ext->SymbolicLinkBuffer;
    *p++ = L'\\'; *p++ = L'D'; *p++ = L'o'; *p++ = L's'; *p++ = L'D'; 
    *p++ = L'e'; *p++ = L'v'; *p++ = L'i'; *p++ = L'c'; *p++ = L'e'; 
    *p++ = L's'; *p++ = L'\\'; *p++ = L'V'; *p++ = L'H'; *p++ = L'I'; 
    *p++ = L'D'; *p++ = L'M'; *p++ = L'o'; *p++ = L'u'; *p++ = L's'; 
    *p++ = L'e'; *p = L'\0';
    
    Ext->SymbolicLink.Buffer = Ext->SymbolicLinkBuffer;
    Ext->SymbolicLink.Length = 21 * sizeof(WCHAR);
    Ext->SymbolicLink.MaximumLength = sizeof(Ext->SymbolicLinkBuffer);
}

// ============================================================================
// Device Creation / Destruction
// ============================================================================

static NTSTATUS CreateVhidDevice(PDRIVER_OBJECT DriverObject)
{
    NTSTATUS status;
    PDEVICE_OBJECT deviceObject = NULL;
    PVHID_EXTENSION ext;
    UNICODE_STRING tempDevName;
    WCHAR tempDevNameBuf[64];
    WCHAR* p;
    
    // Build temporary device name on stack for IoCreateDevice
    p = tempDevNameBuf;
    *p++ = L'\\'; *p++ = L'D'; *p++ = L'e'; *p++ = L'v'; *p++ = L'i'; 
    *p++ = L'c'; *p++ = L'e'; *p++ = L'\\'; *p++ = L'V'; *p++ = L'H'; 
    *p++ = L'I'; *p++ = L'D'; *p++ = L'M'; *p++ = L'o'; *p++ = L'u'; 
    *p++ = L's'; *p++ = L'e'; *p = L'\0';
    
    tempDevName.Buffer = tempDevNameBuf;
    tempDevName.Length = 17 * sizeof(WCHAR);
    tempDevName.MaximumLength = sizeof(tempDevNameBuf);
    
    status = IoCreateDevice(
        DriverObject,
        sizeof(VHID_EXTENSION),
        &tempDevName,
        FILE_DEVICE_UNKNOWN,
        FILE_DEVICE_SECURE_OPEN,
        FALSE,
        &deviceObject
    );
    
    if (!NT_SUCCESS(status)) {
        return status;
    }
    
    ext = (PVHID_EXTENSION)deviceObject->DeviceExtension;
    RtlZeroMemory(ext, sizeof(VHID_EXTENSION));
    ext->Self = deviceObject;
    KeInitializeSpinLock(&ext->Lock);
    
    // Build device strings in extension (relocatable)
    BuildDeviceStrings(ext);
    
    status = IoCreateSymbolicLink(&ext->SymbolicLink, &ext->DeviceName);
    if (!NT_SUCCESS(status)) {
        IoDeleteDevice(deviceObject);
        return status;
    }
    ext->SymbolicLinkCreated = TRUE;

    // Defer mouclass lookup until first open/IOCTL (avoids init-time page faults)
    
    deviceObject->Flags |= DO_BUFFERED_IO;
    deviceObject->Flags &= ~DO_DEVICE_INITIALIZING;
    
    g_Device = deviceObject;
    return STATUS_SUCCESS;
}

static VOID DestroyVhidDevice(VOID)
{
    PVHID_EXTENSION ext;
    
    if (g_Device == NULL) return;
    
    ext = (PVHID_EXTENSION)g_Device->DeviceExtension;
    
    // Use extension-based symbolic link (relocatable)
    if (ext->SymbolicLinkCreated) {
        IoDeleteSymbolicLink(&ext->SymbolicLink);
    }
    
    IoDeleteDevice(g_Device);
    g_Device = NULL;
}

// ============================================================================
// IRP Handlers
// ============================================================================

NTSTATUS VhidCreateClose(PDEVICE_OBJECT DeviceObject, PIRP Irp)
{
    PVHID_EXTENSION ext = (PVHID_EXTENSION)DeviceObject->DeviceExtension;
    
    if (ext->MouseCallback == NULL) {
        (VOID)FindMouseCallback(ext);
    }
    
    Irp->IoStatus.Status = STATUS_SUCCESS;
    Irp->IoStatus.Information = 0;
    IoCompleteRequest(Irp, IO_NO_INCREMENT);
    return STATUS_SUCCESS;
}

NTSTATUS VhidDeviceControl(PDEVICE_OBJECT DeviceObject, PIRP Irp)
{
    NTSTATUS status = STATUS_SUCCESS;
    PIO_STACK_LOCATION irpSp = IoGetCurrentIrpStackLocation(Irp);
    PVHID_EXTENSION ext = (PVHID_EXTENSION)DeviceObject->DeviceExtension;
    PVOID buffer = Irp->AssociatedIrp.SystemBuffer;
    ULONG inLen = irpSp->Parameters.DeviceIoControl.InputBufferLength;
    ULONG code = irpSp->Parameters.DeviceIoControl.IoControlCode;
    
    switch (code) {
        
    case IOCTL_VHID_MOUSE_MOVE:
        if (inLen < sizeof(MOUSE_MOVE_REQUEST)) {
            status = STATUS_BUFFER_TOO_SMALL;
        } else {
            if (ext->MouseCallback == NULL) {
                (VOID)FindMouseCallback(ext);
            }
            status = InjectMouse(ext, (PMOUSE_MOVE_REQUEST)buffer);
        }
        break;
        
    case IOCTL_VHID_SECURE_INPUT:
        if (inLen < sizeof(VHID_SECURE_PACKET)) {
            status = STATUS_BUFFER_TOO_SMALL;
        } else {
            PVHID_SECURE_PACKET pkt = (PVHID_SECURE_PACKET)buffer;
            UCHAR* raw = (UCHAR*)pkt;
            ULONG i;
            
            for (i = 0; i < sizeof(VHID_SECURE_PACKET); i++) {
                raw[i] ^= VHID_ENCRYPTION_KEY;
            }
            
            if (pkt->Type == PacketType_Mouse && pkt->Size == sizeof(MOUSE_MOVE_REQUEST)) {
                if (ext->MouseCallback == NULL) {
                    (VOID)FindMouseCallback(ext);
                }
                status = InjectMouse(ext, (PMOUSE_MOVE_REQUEST)pkt->Payload);
            } else {
                status = STATUS_INVALID_PARAMETER;
            }
        }
        break;
        
    default:
        status = STATUS_INVALID_DEVICE_REQUEST;
        break;
    }
    
    Irp->IoStatus.Status = status;
    Irp->IoStatus.Information = 0;
    IoCompleteRequest(Irp, IO_NO_INCREMENT);
    return status;
}

// ============================================================================
// Driver Entry / Unload
// ============================================================================

VOID DriverUnload(PDRIVER_OBJECT DriverObject)
{
    UNREFERENCED_PARAMETER(DriverObject);
    DestroyVhidDevice();
}

static VOID SetupDriverDispatch(PDRIVER_OBJECT DriverObject)
{
    DriverObject->DriverUnload = DriverUnload;
    DriverObject->MajorFunction[IRP_MJ_CREATE] = VhidCreateClose;
    DriverObject->MajorFunction[IRP_MJ_CLOSE] = VhidCreateClose;
    DriverObject->MajorFunction[IRP_MJ_DEVICE_CONTROL] = VhidDeviceControl;
}

NTSTATUS VhidDriverInitialize(PDRIVER_OBJECT DriverObject, PUNICODE_STRING RegistryPath)
{
    UNREFERENCED_PARAMETER(RegistryPath);

    SetupDriverDispatch(DriverObject);
    return CreateVhidDevice(DriverObject);
}

NTSTATUS DriverEntry(PDRIVER_OBJECT DriverObject, PUNICODE_STRING RegistryPath)
{
    UNREFERENCED_PARAMETER(RegistryPath);

    // Normal load (sc create / SCM): DriverObject is valid.
    if (DriverObject != NULL) {
        return VhidDriverInitialize(DriverObject, RegistryPath);
    }

    // Manual map (kdmapper, NeacMapLoader): DriverObject is NULL.
    // Resolve IoCreateDriver at runtime in case kdmapper botched the IAT.
    {
        FN_IoCreateDriver createDriver = ResolveIoCreateDriver();
        if (createDriver == NULL) {
            return STATUS_PROCEDURE_NOT_FOUND;
        }
        return createDriver(NULL, VhidDriverInitialize);
    }
}
