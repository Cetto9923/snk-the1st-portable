import struct
import unittest

from scripts.graphics.compile_dumped_shaders import compute_metadata, localize_1618_scratch
from scripts.graphics.build_ffrs_xgs import instructions


class ComputeMetadataTests(unittest.TestCase):
    def control(self, local, shared=0):
        control = bytearray(0x880)
        struct.pack_into('<3I', control, 0x748, *local)
        struct.pack_into('<I', control, 0x754, shared)
        return control

    def test_uses_original_nvn_workgroup_dimensions(self):
        # These differ from the translator's default and cover the lighting
        # shaders' three-dimensional local invocation coordinates.
        metadata = compute_metadata(self.control((4, 8, 2), 1792))
        self.assertEqual(metadata, {'local': [4, 8, 2], 'shared': 1792})

    def test_keeps_original_512_thread_group(self):
        metadata = compute_metadata(self.control((512, 1, 1)))
        self.assertEqual(metadata['local'], [512, 1, 1])

    def test_rounds_shared_memory_to_sixteen_bytes(self):
        self.assertEqual(compute_metadata(self.control((8, 8, 1), 17))['shared'], 32)

    def test_rejects_truncated_control(self):
        with self.assertRaisesRegex(ValueError, 'shorter'):
            compute_metadata(bytes(0x757))

    def test_rejects_zero_dimension(self):
        with self.assertRaisesRegex(ValueError, 'zero workgroup'):
            compute_metadata(self.control((8, 0, 1)))


class InvocationScratchTests(unittest.TestCase):
    def module(self, stride=44, offset=4, second_store=False, escape=False,
               conditional_store=False, non_integer=False):
        words = [0x07230203, 0x00010300, 0, 1000, 0]

        def emit(opcode, *operands):
            words.extend([(len(operands) + 1) << 16 | opcode, *operands])

        emit(17, 1)  # Shader
        emit(14, 0, 1)  # Logical GLSL450
        emit(15, 5, 200, 0x6e69616d, 0, 100)  # GLCompute main
        emit(16, 200, 17, 1024, 1, 1)
        emit(71, 100, 11, 27)  # LocalInvocationId
        emit(19, 1)  # void
        emit(21, 2, 32, 0)  # uint
        emit(23, 3, 2, 3)  # uvec3
        emit(32, 4, 1, 3)  # Input uvec3*
        emit(32, 5, 1, 2)  # Input uint*
        emit(43, 2, 6, 11264)
        emit(28, 7, 2, 6)
        emit(32, 8, 4, 7)  # Workgroup uint[11264]*
        emit(32, 9, 4, 2)  # Workgroup uint*
        emit(32, 10, 7, 2)  # Function uint*
        emit(33, 11, 1)
        for identifier, value in ((12, 0), (13, stride), (14, offset), (15, 2)):
            emit(43, 2, identifier, value)
        emit(20, 18)
        emit(41, 18, 19)
        emit(22, 20, 32)  # float, used by the invalid arithmetic fixture
        emit(59, 4, 100, 1)
        emit(59, 8, 101, 4)
        emit(54, 1, 200, 0, 11)
        emit(248, 201)
        emit(59, 10, 202, 7)
        emit(65, 5, 203, 100, 12)
        emit(61, 2, 204, 203)
        emit(132, 20 if non_integer else 2, 205, 204, 13)
        if conditional_store:
            emit(247, 212, 0)
            emit(250, 19, 210, 211)
            emit(248, 210)
        emit(62, 202, 205)
        if second_store:
            emit(62, 202, 204)
        if conditional_store:
            emit(249, 212)
            emit(248, 211)
            emit(249, 212)
            emit(248, 212)
        emit(61, 2, 206, 202)
        emit(128, 2, 207, 206, 14)
        emit(194, 2, 208, 207, 15)
        for index in range(34):
            emit(65, 9, 300 + index, 101, 208)
            emit(62, 300 + index, 12)
        if escape:
            emit(83, 8, 500, 101)
        emit(253)
        emit(56)
        return words

    def test_localizes_all_accesses_and_keeps_other_instructions(self):
        before = self.module()
        after, report = localize_1618_scratch(before)
        self.assertEqual(report, {'accesses': 34, 'workgroup_bytes_before': 45056,
                                  'workgroup_bytes_after': 0,
                                  'private_bytes_per_invocation': 44})
        original = [(op, ops) for _, op, ops in instructions(before)]
        lowered = [(op, ops) for _, op, ops in instructions(after)]
        constants = {ops[1]: ops[2] for op, ops in lowered if op == 43}
        private = [ops for op, ops in lowered if op == 59 and ops[1] == 101]
        self.assertEqual(private[0][2], 6)
        accesses = [ops for op, ops in lowered if op == 65 and ops[2] == 101]
        self.assertEqual(len(accesses), 34)
        self.assertEqual({constants[ops[3]] for ops in accesses}, {1})
        # Every invocation keeps the same word within its disjoint slice.
        for invocation in range(1024):
            self.assertEqual((invocation * 44 + 4) // 4 - invocation * 11,
                             constants[accesses[0][3]])
        unchanged_before = [(op, ops) for op, ops in original
                            if not (op == 59 and ops[1] == 101) and
                            not (op == 65 and ops[2] == 101)]
        unchanged_after = [(op, ops) for op, ops in lowered
                           if not (ops and ops[0] >= before[3]) and
                           not (op == 43 and ops[1] >= before[3]) and
                           not (op == 59 and ops[1] == 101) and
                           not (op == 65 and ops[2] == 101)]
        self.assertEqual(unchanged_after, unchanged_before)

    def test_rejects_cross_invocation_and_out_of_bounds_accesses(self):
        for arguments in ({'stride': 48}, {'offset': 44}):
            with self.subTest(arguments=arguments), self.assertRaisesRegex(ValueError, 'invocation-local'):
                localize_1618_scratch(self.module(**arguments))

    def test_preserves_each_of_eleven_words_for_all_1024_invocations(self):
        for byte_offset in range(0, 44, 4):
            with self.subTest(byte_offset=byte_offset):
                after, _ = localize_1618_scratch(self.module(offset=byte_offset))
                parsed = [(op, ops) for _, op, ops in instructions(after)]
                constants = {ops[1]: ops[2] for op, ops in parsed if op == 43}
                indices = {constants[ops[3]] for op, ops in parsed
                           if op == 65 and ops[2] == 101}
                self.assertEqual(indices, {byte_offset // 4})
                for invocation in range(1024):
                    self.assertEqual((invocation * 44 + byte_offset) // 4,
                                     invocation * 11 + next(iter(indices)))

    def test_rejects_escaping_and_multiply_written_pointers(self):
        for arguments in ({'escape': True}, {'second_store': True}):
            with self.subTest(arguments=arguments), self.assertRaises(ValueError):
                localize_1618_scratch(self.module(**arguments))

    def test_rejects_store_that_does_not_dominate_load(self):
        with self.assertRaisesRegex(ValueError, 'dominate'):
            localize_1618_scratch(self.module(conditional_store=True))

    def test_rejects_non_integer_address_arithmetic(self):
        with self.assertRaisesRegex(ValueError, '32-bit integers'):
            localize_1618_scratch(self.module(non_integer=True))


if __name__ == '__main__':
    unittest.main()
