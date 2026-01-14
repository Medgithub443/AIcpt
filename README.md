# Unpacket

**Unpacket** is a pure Python utility designed to decrypt Cisco Packet Tracer (`.pkt`) files and convert them into readable XML format. 

This tool is particularly useful for security researchers and network enthusiasts who want to analyze the internal structure of Packet Tracer lab files without relying on the official software.

## Features

- **Dependency-Free**: Implemented using pure Python. It does not require external libraries.
- **Custom Cryptography**: Includes standalone implementations of:
  - **Twofish** block cipher.
  - **EAX** mode of operation.
  - **CMAC** and **CTR** modes.
- **Stage Deobfuscation**: Handles the proprietary multi-stage obfuscation layers used by Cisco.
- **CLI Interface**: Easy-to-use command-line interface with `argparse`.

## Installation

No installation is required. Just clone the repository and ensure you have Python 3.x installed.

```bash
git clone https://github.com/yourusername/unpacket.git
cd unpacket
```

## Usage

To decrypt a `.pkt` file, simply run:

```bash
python3 unpacket.py your_lab_file.pkt
```

By default, the decrypted file will be saved as `your_lab_file.xml`. You can also specify a custom output path:

```bash
python3 unpacket.py input.pkt 
(optional) python3 unpacket.py input.pkt -o custom_output.xml
```

To encypt a `.xml` file into `.pkt`, run:

```bash
python3 repacket.py input.xml 
(optional) python3 repacket.py input.xml -o custom_output.pkt
```
## Command Line Options

### Unpacket

| Option           | Description                             |
| ---------------- | --------------------------------------- |
| `input_file`     | Path to the `.pkt` file to decrypt.     |
| `-o`, `--output` | (Optional) Path to the output XML file. |
| `-h`, `--help`   | Show the help message and exit.         |
### Repacket

| Option           | Description                                |
| ---------------- | ------------------------------------------ |
| `input_file`     | Path to the `.xml` file to encrypt.        |
| `-o`, `--output` | (Optional) Path to the output `.pkt` file. |
| `-h`, `--help`   | Show the help message and exit.            |

## Technical Details

The decryption process follows several steps:
1. **Stage 1 Deobfuscation**: A byte-wise XOR and reversal operation.
2. **EAX Decryption**: Decrypting the payload using the Twofish cipher in EAX mode (Authenticated Encryption).
3. **Stage 2 Deobfuscation**: A secondary XOR-based transformation.
4. **Zlib Decompression**: Extracting the final XML content from the compressed blob.

## Disclaimer

This tool is intended for **educational and research purposes only**. Use it responsibly. The authors are not responsible for any misuse or damage caused by this software. All product names, logos, and brands are property of their respective owners.

## License

This project is licensed under the MIT License.
