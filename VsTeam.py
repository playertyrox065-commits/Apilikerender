import os, sys
import requests
import time, datetime
import asyncio, aiohttp
import base64, json, jwt

from protobuf import my_message_pb2
from datetime import datetime
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad, unpad
from google.protobuf.timestamp_pb2 import Timestamp
from protobuf_decoder.protobuf_decoder import Parser


class VsTeam:
    def __init__(self):
        pass

    def fix_hex(self, hex_str):
        hex_str = hex_str.lower().replace(" ", "")
        return hex_str

    def dec_to_hex(self, decimal):
        decimal = hex(decimal)
        final_result = str(decimal)[2:]
        if len(final_result) == 1:
            final_result = "0" + final_result
            return final_result
        else:
            return final_result

    def encode_varint(self, number):
        if number < 0:
            raise ValueError("Number must be non-negative")

        encoded_bytes = []

        while True:
            byte = number & 0x7F
            number >>= 7

            if number:
                byte |= 0x80
            encoded_bytes.append(byte)

            if not number:
                break

        return bytes(encoded_bytes)

    def create_varint_field(self, field_number, value):
        field_header = (field_number << 3) | 0  # Varint wire type = 0
        return self.encode_varint(field_header) + self.encode_varint(value)

    def create_length_delimited_field(self, field_number, value):
        field_header = (field_number << 3) | 2  # Length-delimited wire type = 2
        encoded_value = value.encode() if isinstance(value, str) else value
        return (
            self.encode_varint(field_header)
            + self.encode_varint(len(encoded_value))
            + encoded_value
        )

    def create_protobuf_packet(self, fields):
        packet = bytearray()

        for field, value in fields.items():
            if isinstance(value, dict):
                nested_packet = self.create_protobuf_packet(value)
                packet.extend(self.create_length_delimited_field(field, nested_packet))

            elif isinstance(value, int):
                packet.extend(self.create_varint_field(field, value))

            elif isinstance(value, (str, bytes)):
                packet.extend(self.create_length_delimited_field(field, value))

        return packet

    def parse_my_message(self, serialized_data):
        my_message = my_message_pb2.MyMessage()
        my_message.ParseFromString(serialized_data)

        timestamp = my_message.field21
        key = my_message.field22
        iv = my_message.field23

        timestamp_obj = Timestamp()
        timestamp_obj.FromNanoseconds(timestamp)

        timestamp_seconds = timestamp_obj.seconds
        timestamp_nanos = timestamp_obj.nanos

        combined_timestamp = timestamp_seconds * 1_000_000_000 + timestamp_nanos
        return combined_timestamp, key, iv

    def parse_results(self, parsed_results):
        result_dict = {}

        for result in parsed_results:
            field_data = {}
            field_data["wire_type"] = result.wire_type

            if result.wire_type in ("varint", "string", "bytes"):
                field_data["data"] = result.data

            elif result.wire_type == "length_delimited":
                field_data["data"] = self.parse_results(result.data.results)

            result_dict[result.field] = field_data

        return result_dict

    def parsed_results_to_dict(self, parsed_results):
        result_dict = {}

        for parsed_result in parsed_results.results:
            if hasattr(parsed_result.data, "results"):
                result_dict[parsed_result.field] = self.parsed_results_to_dict(parsed_result.data)
            else:
                result_dict[parsed_result.field] = parsed_result.data

        return result_dict
