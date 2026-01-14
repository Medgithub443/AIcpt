#!/usr/bin/env python3
import argparse
import sys
import os
import zlib
import struct
from Decipher.eax import EAX
from Decipher.twofish import Twofish

def banner():
    print("==============================================")
    print("  Repacket - Cisco Packet Tracer Encryptor    ")
    print("==============================================")

def compress_qt(xml_data: bytes) -> bytes:
    """
    Compresses data using zlib and prepends the original size (4 bytes big-endian).
    Inverse operation of uncompress_qt.
    """
    # 1. Calculate original size
    size = len(xml_data)
    # 2. Create header (4 bytes big-endian)
    header = struct.pack(">I", size)
    # 3. Compress data (zlib default)
    compressed = zlib.compress(xml_data)
    return header + compressed

def obf_stage2(data: bytes) -> bytes:
    """
    Applies Stage 2 obfuscation.
    Since it is an XOR operation, it is symmetric: A ^ B = C => C ^ B = A.
    Original logic: b ^ (L - i & 0xFF)
    """
    L = len(data)
    return bytes(b ^ (L - i & 0xFF) for i, b in enumerate(data))

def obf_stage1(data: bytes) -> bytes:
    """
    Applies Stage 1 obfuscation (inverse of deobfuscation).
    
    Unpacket logic (Deobf):
       result[i] = input[L-1-i] ^ Key(i)
       
    Repacket logic (Obf):
       We need to find input[k].
       Let k = L-1-i. Then i = L-1-k.
       input[k] = result[L-1-k] ^ Key(L-1-k)
       
    Basically: take clear byte 'b' at index 'i', XOR it with the key 
    calculated for 'i', and place the result at the end of the output buffer, 
    filling backwards.
    """
    L = len(data)
    output = bytearray(L)
    
    for i in range(L):
        # The key depends on the length and the index 'i' of the clear data
        key_byte = (L - i*L) & 0xFF
        val = data[i] ^ key_byte
        
        # Place result mirror-wise
        output[L-1-i] = val
        
    return bytes(output)

def encrypt_pkt(data: bytes) -> bytes:
    """
    Encrypts data using Twofish in EAX mode.
    """
    # Hardcoded Key and IV for .pkt files (same as unpacket)
    key = bytes([137])*16
    iv  = bytes([16])*16

    # Initialize Twofish
    tf = Twofish(key)
    
    # Initialize EAX in encrypt mode
    # Note: EAX takes the block encryption function
    eax = EAX(tf.encrypt)

    # Encrypt and generate tag
    ciphertext, tag = eax.encrypt(nonce=iv, plaintext=data)

    # In .pkt files, the tag is appended at the end of the ciphertext
    return ciphertext + tag

def main():
    banner()
    
    parser = argparse.ArgumentParser(
        description="Encrypts XML files back to Cisco Packet Tracer (.pkt) format."
    )
    parser.add_argument(
        "input_file", 
        help="Path to the .xml file to encrypt."
    )
    parser.add_argument(
        "-o", "--output", 
        help="Path to the output .pkt file. Defaults to <input_file>.pkt",
        default=None
    )

    args = parser.parse_args()
    input_path = args.input_file

    if not os.path.exists(input_path):
        print(f"[-] Error: Input file '{input_path}' not found.")
        sys.exit(1)

    # Determine output path
    if args.output:
        output_path = args.output
    else:
        if input_path.lower().endswith(".xml"):
            output_path = input_path[:-4] + ".pkt"
        else:
            output_path = input_path + ".pkt"

    print(f"[*] Reading XML '{input_path}'...")
    try:
        with open(input_path, "rb") as f:
            xml_data = f.read()
    except IOError as e:
        print(f"[-] Error reading file: {e}")
        sys.exit(1)

    # Reverse pipeline
    try:
        print("[*] Compressing data (zlib)...")
        stage2_input = compress_qt(xml_data)

        print("[*] Applying Stage 2 Obfuscation...")
        decrypted_blob = obf_stage2(stage2_input)

        print("[*] Encrypting (Twofish/EAX)...")
        stage1_input = encrypt_pkt(decrypted_blob)

        print("[*] Applying Stage 1 Obfuscation...")
        final_pkt_data = obf_stage1(stage1_input)

    except Exception as e:
        print(f"[-] Encryption/Obfuscation failed: {e}")
        sys.exit(1)

    print(f"[*] Writing encrypted data to '{output_path}'...")
    try:
        with open(output_path, "wb") as f:
            f.write(final_pkt_data)
    except IOError as e:
        print(f"[-] Error writing output file: {e}")
        sys.exit(1)

    print("[+] Success! File repacketed.")

if __name__ == "__main__":
    main()
