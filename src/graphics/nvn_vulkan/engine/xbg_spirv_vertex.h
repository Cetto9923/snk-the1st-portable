#pragma once
#include <array>
#include <cstddef>
#include <cstdint>
#include <map>
#include <vector>

// Match integer vertex formats while preserving Maxwell's register bits.
// Each location has two mask bits, 1 for UINT and 2 for SINT. The existing
// translated arithmetic still receives its original FP32 bit patterns.
inline int xbg_spirv_integer_vertex_inputs(std::vector<uint32_t> &words, uint32_t kinds) {
    if (!kinds) return 0;
    if (words.size() < 5 || words[0] != 0x07230203u) return -1;
    std::vector<size_t> instructions;
    std::map<uint32_t, uint32_t> locations, pointers;
    std::map<uint32_t, std::array<uint32_t, 2>> vectors;
    uint32_t float_type = 0;
    struct Types { uint32_t scalar = 0, vector = 0, scalar_pointer = 0, vector_pointer = 0; };
    Types types[3];
    for (size_t offset = 5; offset < words.size();) {
        uint32_t count = words[offset] >> 16, op = words[offset] & 65535;
        if (!count || count > words.size() - offset) return -1;
        instructions.push_back(offset);
        if (op == 22 && count == 3 && words[offset + 2] == 32) float_type = words[offset + 1];
        if (op == 21 && count == 4 && words[offset + 2] == 32 && words[offset + 3] <= 1)
            types[words[offset + 3] ? 2 : 1].scalar = words[offset + 1];
        if (op == 23 && count == 4)
            vectors[words[offset + 1]] = {words[offset + 2], words[offset + 3]};
        if (op == 32 && count == 4 && words[offset + 2] == 1)
            pointers[words[offset + 1]] = words[offset + 3];
        if (op == 71 && count == 4 && words[offset + 2] == 30)
            locations[words[offset + 1]] = words[offset + 3];
        offset += count;
    }
    uint32_t float_vector = 0;
    for (const auto &entry : vectors) {
        if (entry.second == std::array<uint32_t, 2>{float_type, 4}) float_vector = entry.first;
        for (unsigned kind = 1; kind <= 2; ++kind)
            if (entry.second == std::array<uint32_t, 2>{types[kind].scalar, 4}) types[kind].vector = entry.first;
    }
    if (!float_type || !float_vector) return -1;
    struct Input { uint32_t kind, pointee; };
    std::map<uint32_t, Input> inputs;
    std::map<uint32_t, uint32_t> variables;
    for (size_t offset : instructions) {
        if ((words[offset] & 65535) != 59 || (words[offset] >> 16) != 4 || words[offset + 3] != 1) continue;
        auto location = locations.find(words[offset + 2]);
        if (location == locations.end() || location->second >= 16) continue;
        uint32_t kind = (kinds >> (2 * location->second)) & 3;
        if (!kind) continue;
        auto pointer = pointers.find(words[offset + 1]);
        if (kind <= 2 && pointer != pointers.end() && types[kind].vector && pointer->second == types[kind].vector) continue;
        if (kind > 2 || pointer == pointers.end() || pointer->second != float_vector) return -1;
        inputs.emplace(words[offset + 2], Input{kind, float_vector});
        variables.emplace(words[offset + 2], kind);
    }
    if (variables.empty()) return 0;
    // Follow Input pointers without changing any arithmetic or descriptor.
    for (size_t offset : instructions) {
        uint32_t op = words[offset] & 65535, count = words[offset] >> 16;
        if ((op == 65 || op == 66 || op == 83) && count >= 4) {
            auto base = inputs.find(words[offset + 3]);
            if (base == inputs.end()) continue;
            auto pointer = pointers.find(words[offset + 1]);
            if (pointer == pointers.end() || (pointer->second != float_type && pointer->second != float_vector)) return -1;
            inputs.emplace(words[offset + 2], Input{base->second.kind, pointer->second});
        }
        if (op == 62 && count >= 3 && (inputs.count(words[offset + 1]) || inputs.count(words[offset + 2]))) return -1;
        if (op == 57) for (uint32_t index = 4; index < count; ++index)
            if (inputs.count(words[offset + index])) return -1;
        if (op == 245) for (uint32_t index = 3; index < count; index += 2)
            if (inputs.count(words[offset + index])) return -1;
        if (op == 169 && count >= 6 && (inputs.count(words[offset + 4]) || inputs.count(words[offset + 5]))) return -1;
        if (op == 67 && count >= 4 && inputs.count(words[offset + 3])) return -1;
        if (op == 61 && count >= 4) {
            auto input = inputs.find(words[offset + 3]);
            if (input != inputs.end() && words[offset + 1] != input->second.pointee) return -1;
        }
    }
    uint32_t bound = words[3];
    std::vector<uint32_t> declarations, moved_variables;
    bool used[3] = {};
    for (const auto &entry : variables) used[entry.second] = true;
    for (unsigned kind = 1; kind <= 2; ++kind) {
        if (!used[kind]) continue;
        Types &type = types[kind];
        if (!type.scalar) {
            type.scalar = bound++;
            declarations.insert(declarations.end(), {4u << 16 | 21u, type.scalar, 32, kind == 2 ? 1u : 0u});
        }
        if (!type.vector) {
            type.vector = bound++;
            declarations.insert(declarations.end(), {4u << 16 | 23u, type.vector, type.scalar, 4});
        }
        for (const auto &pointer : pointers) {
            if (pointer.second == type.scalar) type.scalar_pointer = pointer.first;
            if (pointer.second == type.vector) type.vector_pointer = pointer.first;
        }
        if (!type.scalar_pointer) {
            type.scalar_pointer = bound++;
            declarations.insert(declarations.end(), {4u << 16 | 32u, type.scalar_pointer, 1, type.scalar});
        }
        if (!type.vector_pointer) {
            type.vector_pointer = bound++;
            declarations.insert(declarations.end(), {4u << 16 | 32u, type.vector_pointer, 1, type.vector});
        }
    }
    std::vector<uint32_t> output(words.begin(), words.begin() + 5);
    bool inserted = false;
    for (size_t offset : instructions) {
        uint32_t count = words[offset] >> 16, op = words[offset] & 65535;
        if (op == 59 && count >= 4 && variables.count(words[offset + 2])) {
            uint32_t kind = variables.at(words[offset + 2]);
            moved_variables.insert(moved_variables.end(), {4u << 16 | 59u, types[kind].vector_pointer, words[offset + 2], 1});
            continue;
        }
        if (op == 54 && !inserted) {
            output.insert(output.end(), declarations.begin(), declarations.end());
            output.insert(output.end(), moved_variables.begin(), moved_variables.end());
            inserted = true;
        }
        size_t start = output.size();
        output.insert(output.end(), words.begin() + offset, words.begin() + offset + count);
        if ((op == 65 || op == 66 || op == 83) && count >= 4 && inputs.count(words[offset + 2])) {
            const Input &input = inputs.at(words[offset + 2]);
            output[start + 1] = input.pointee == float_type ? types[input.kind].scalar_pointer : types[input.kind].vector_pointer;
        }
        if (op == 61 && count >= 4 && inputs.count(words[offset + 3])) {
            const Input &input = inputs.at(words[offset + 3]);
            uint32_t raw = bound++;
            output[start + 1] = input.pointee == float_type ? types[input.kind].scalar : types[input.kind].vector;
            output[start + 2] = raw;
            output.insert(output.end(), {4u << 16 | 124u, words[offset + 1], words[offset + 2], raw});
        }
    }
    if (!inserted) return -1;
    output[3] = bound;
    words.swap(output);
    return int(variables.size());
}
