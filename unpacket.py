#!/usr/bin/env python3
import argparse
import sys
import os
import xml.etree.ElementTree as ET
from Decipher.pt_crypto import decrypt_pkt

def banner():
    print("==============================================")
    print("  Unpacket - Cisco Packet Tracer Decryptor    ")
    print("==============================================")

def main():
    banner()
    
    parser = argparse.ArgumentParser(
        description="Decrypts Cisco Packet Tracer (.pkt) files to XML format."
    )
    parser.add_argument(
        "input_file", 
        help="Path to the .pkt file to decrypt."
    )
    parser.add_argument(
        "-o", "--output", 
        help="Path to the output XML file. Defaults to <input_file>.xml",
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
        # If input ends with .pkt, strip it; otherwise append .xml
        if input_path.lower().endswith(".pkt"):
            output_path = input_path[:-4] + ".xml"
        else:
            output_path = input_path + ".xml"

    print(f"[*] Reading '{input_path}'...")
    try:
        with open(input_path, "rb") as f:
            data = f.read()
    except IOError as e:
        print(f"[-] Error reading file: {e}")
        sys.exit(1)

    print("[*] Decrypting...")
    try:
        xml_data = decrypt_pkt(data)
    except Exception as e:
        print(f"[-] Decryption failed: {e}")
        sys.exit(1)

    print("[*] Parsing XML...")
    try:
        root = ET.fromstring(xml_data)
        tree = ET.ElementTree(root)
        if hasattr(ET, "indent"):
            ET.indent(tree, space="  ")
    except ET.ParseError as e:
        print(f"[-] XML Parsing failed: {e}")
        sys.exit(1)

    print(f"[*] Writing decrypted data to '{output_path}'...")
    try:
        tree.write(output_path, encoding="utf-8", xml_declaration=True)
    except IOError as e:
        print(f"[-] Error writing output file: {e}")
        sys.exit(1)

    print("[+] Success! Decryption complete.")

if __name__ == "__main__":
    main()
