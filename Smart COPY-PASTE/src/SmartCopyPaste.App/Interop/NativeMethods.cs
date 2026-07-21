using System.ComponentModel;
using System.Runtime.InteropServices;

namespace SmartCopyPaste.App.Interop;

internal static class NativeMethods
{
    internal const int WmHotkey = 0x0312;
    internal const uint InputKeyboard = 1;
    internal const uint KeyeventfKeyup = 0x0002;
    internal const uint KeyeventfUnicode = 0x0004;
    internal const int VkControl = 0x11;
    internal const int VkShift = 0x10;
    internal const int VkMenu = 0x12;
    internal const int VkLwin = 0x5B;
    internal const int VkRwin = 0x5C;

    [DllImport("user32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    internal static extern bool RegisterHotKey(nint windowHandle, int id, uint modifiers, uint virtualKey);

    [DllImport("user32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    internal static extern bool UnregisterHotKey(nint windowHandle, int id);

    [DllImport("user32.dll")]
    internal static extern nint GetForegroundWindow();

    [DllImport("user32.dll")]
    [return: MarshalAs(UnmanagedType.Bool)]
    internal static extern bool SetForegroundWindow(nint windowHandle);

    [DllImport("user32.dll")]
    internal static extern uint GetWindowThreadProcessId(nint windowHandle, out uint processId);

    [DllImport("user32.dll")]
    internal static extern short GetAsyncKeyState(int virtualKey);

    [DllImport("user32.dll", SetLastError = true)]
    internal static extern uint SendInput(uint inputCount, Input[] inputs, int inputSize);

    [DllImport("user32.dll")]
    internal static extern uint GetClipboardSequenceNumber();

    [DllImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    internal static extern bool AttachConsole(uint processId);

    [DllImport("ole32.dll", CharSet = CharSet.Unicode)]
    internal static extern int CLSIDFromProgID(string programmaticId, out Guid classId);

    [DllImport("oleaut32.dll", PreserveSig = true)]
    internal static extern int GetActiveObject(
        ref Guid classId,
        nint reserved,
        [MarshalAs(UnmanagedType.IUnknown)] out object activeObject);

    [DllImport("crypt32.dll", SetLastError = true, CharSet = CharSet.Unicode)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool CryptProtectData(
        ref DataBlob dataIn,
        string? description,
        nint optionalEntropy,
        nint reserved,
        nint promptStructure,
        uint flags,
        out DataBlob dataOut);

    [DllImport("crypt32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool CryptUnprotectData(
        ref DataBlob dataIn,
        nint description,
        nint optionalEntropy,
        nint reserved,
        nint promptStructure,
        uint flags,
        out DataBlob dataOut);

    [DllImport("kernel32.dll")]
    private static extern nint LocalFree(nint memory);

    internal static object GetActiveComObject(string programmaticId)
    {
        int classResult = CLSIDFromProgID(programmaticId, out Guid classId);
        Marshal.ThrowExceptionForHR(classResult);
        int activeResult = GetActiveObject(ref classId, nint.Zero, out object activeObject);
        Marshal.ThrowExceptionForHR(activeResult);
        return activeObject;
    }

    internal static byte[] ProtectCurrentUser(byte[] plaintext)
    {
        ArgumentNullException.ThrowIfNull(plaintext);
        return TransformData(plaintext, protect: true);
    }

    internal static byte[] UnprotectCurrentUser(byte[] ciphertext)
    {
        ArgumentNullException.ThrowIfNull(ciphertext);
        return TransformData(ciphertext, protect: false);
    }

    internal static bool AreShortcutModifiersReleased() =>
        !IsPressed(VkControl) &&
        !IsPressed(VkShift) &&
        !IsPressed(VkMenu) &&
        !IsPressed(VkLwin) &&
        !IsPressed(VkRwin);

    internal static void ThrowIfSendInputIncomplete(Input[] inputs)
    {
        uint sent = SendInput((uint)inputs.Length, inputs, Marshal.SizeOf<Input>());
        if (sent != inputs.Length)
        {
            throw new Win32Exception(Marshal.GetLastPInvokeError(), "Windows did not accept all simulated input events.");
        }
    }

    private static bool IsPressed(int virtualKey) => (GetAsyncKeyState(virtualKey) & 0x8000) != 0;

    private static byte[] TransformData(byte[] source, bool protect)
    {
        nint inputMemory = Marshal.AllocHGlobal(source.Length);
        try
        {
            Marshal.Copy(source, 0, inputMemory, source.Length);
            DataBlob input = new() { Size = source.Length, Data = inputMemory };
            bool succeeded;
            DataBlob output;

            if (protect)
            {
                succeeded = CryptProtectData(
                    ref input,
                    "Smart COPY/PASTE per-user secret",
                    nint.Zero,
                    nint.Zero,
                    nint.Zero,
                    0x1,
                    out output);
            }
            else
            {
                succeeded = CryptUnprotectData(
                    ref input,
                    nint.Zero,
                    nint.Zero,
                    nint.Zero,
                    nint.Zero,
                    0x1,
                    out output);
            }

            if (!succeeded)
            {
                throw new Win32Exception(Marshal.GetLastPInvokeError());
            }

            try
            {
                byte[] result = new byte[output.Size];
                Marshal.Copy(output.Data, result, 0, output.Size);
                return result;
            }
            finally
            {
                _ = LocalFree(output.Data);
            }
        }
        finally
        {
            Marshal.FreeHGlobal(inputMemory);
        }
    }

    [StructLayout(LayoutKind.Sequential)]
    internal struct Input
    {
        internal uint Type;
        internal InputUnion Data;
    }

    [StructLayout(LayoutKind.Explicit)]
    internal struct InputUnion
    {
        [FieldOffset(0)]
        internal KeyboardInput Keyboard;

        // INPUT's native union is sized by MOUSEINPUT (32 bytes on x64).
        // Keeping this member is required even though this application sends
        // keyboard input only; otherwise cbSize is rejected by SendInput.
        [FieldOffset(0)]
        internal MouseInput Mouse;

        [FieldOffset(0)]
        internal HardwareInput Hardware;
    }

    [StructLayout(LayoutKind.Sequential)]
    internal struct KeyboardInput
    {
        internal ushort VirtualKey;
        internal ushort ScanCode;
        internal uint Flags;
        internal uint Time;
        internal nuint ExtraInfo;
    }

    [StructLayout(LayoutKind.Sequential)]
    internal struct MouseInput
    {
        internal int X;
        internal int Y;
        internal uint MouseData;
        internal uint Flags;
        internal uint Time;
        internal nuint ExtraInfo;
    }

    [StructLayout(LayoutKind.Sequential)]
    internal struct HardwareInput
    {
        internal uint Message;
        internal ushort ParameterLow;
        internal ushort ParameterHigh;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct DataBlob
    {
        internal int Size;
        internal nint Data;
    }
}
