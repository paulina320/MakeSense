import unittest

import numpy as np

from hardware.serial_protocol import (
    MessageType,
    PacketParser,
    TextLine,
    command,
    encode_frame,
    pack_i16_samples,
    unpack_imu_sample,
    unpack_imu_samples,
    unpack_i16_samples,
)


class SerialProtocolTests(unittest.TestCase):
    def test_frame_round_trip(self):
        payload = b"abc123"
        parser = PacketParser()
        parsed = parser.feed(encode_frame(MessageType.SAMPLES, 7, payload))
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0].message_type, MessageType.SAMPLES)
        self.assertEqual(parsed[0].sequence, 7)
        self.assertEqual(parsed[0].payload, payload)

    def test_resync_after_garbage(self):
        parser = PacketParser()
        data = b"garbage" + encode_frame(MessageType.ERROR, 2, b"oops")
        parsed = parser.feed(data)
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0].payload, b"oops")
        self.assertGreaterEqual(parser.resync_count, 1)

    def test_crc_failure_is_dropped(self):
        parser = PacketParser()
        frame = bytearray(encode_frame(MessageType.SAMPLES, 1, b"bad"))
        frame[-1] ^= 0xFF
        parsed = parser.feed(bytes(frame))
        self.assertEqual(parsed, [])
        self.assertEqual(parser.crc_failures, 1)

    def test_mixed_text_and_frame(self):
        parser = PacketParser()
        parsed = parser.feed(b"OK PONG\n" + encode_frame(MessageType.STATUS, 3, b"{}"))
        self.assertIsInstance(parsed[0], TextLine)
        self.assertEqual(parsed[0].text, "OK PONG")
        self.assertEqual(parsed[1].message_type, MessageType.STATUS)

    def test_sample_pack_unpack(self):
        samples = np.array([-1.0, -0.5, 0.0, 0.5, 1.0], dtype=np.float32)
        unpacked = unpack_i16_samples(pack_i16_samples(samples))
        np.testing.assert_allclose(unpacked, samples, atol=1 / 32767)

    def test_command_encoding(self):
        self.assertEqual(command("ping"), b"PING\n")
        self.assertEqual(command("config_stream", 44100, "0,1"), b"CONFIG_STREAM 44100 0,1\n")

    def test_imu_sample_unpack(self):
        payload = (
            (123456).to_bytes(4, "little")
            + bytes([0x1F, 0])
            + np.array([1, 2, 3, 4, 5, 6, 7, 8, 9], dtype="<i2").tobytes()
            + np.array([1000, 2000], dtype="<i4").tobytes()
        )
        sample = unpack_imu_sample(payload)
        self.assertEqual(sample["timestamp_us"], 123456)
        self.assertTrue(sample["ok"])
        np.testing.assert_allclose(sample["accel"], [0.0039, 0.0078, 0.0117])
        self.assertEqual(sample["accel_raw"], [1, 2, 3])
        self.assertEqual(sample["accel_unit"], "g")
        self.assertEqual(sample["gyro"], [4, 5, 6])
        self.assertEqual(sample["mag"], [7, 8, 9])
        self.assertEqual(sample["bmp_pressure_raw"], 1000)
        self.assertEqual(sample["bmp_temperature_raw"], 2000)

    def test_imu_sample_batch_unpack(self):
        one = (
            (1).to_bytes(4, "little")
            + bytes([0x03, 0])
            + np.array([1, 2, 3, 4, 5, 6, 7, 8, 9], dtype="<i2").tobytes()
            + np.array([10, 11], dtype="<i4").tobytes()
        )
        samples = unpack_imu_samples(one + one)
        self.assertEqual(len(samples), 2)
        self.assertEqual(samples[0]["timestamp_us"], 1)
        np.testing.assert_allclose(samples[1]["accel"], [0.0039, 0.0078, 0.0117])


if __name__ == "__main__":
    unittest.main()
