from BinaryReader import *
from StringTableReader import *
from munch import Munch

class SerializedFileReader:

    streader = StringTableReader()

    def read(self, file):
        r = BinaryReader(file)
        sf = Munch()
        self.read_header(r, sf)
        self.read_types(r, sf)
        self.read_objects(r, sf)
        if sf.header.version > 10:
            self.read_script_types(r, sf)
        self.read_externals(r, sf)

        return sf

    def read_header(self, r, sf):
        # the header always uses big-endian byte order
        r.be = True

        sf.header = Munch()
        sf.header.metadataSize = r.read_int32()
        sf.header.fileSize = r.read_int32()
        sf.header.version = r.read_int32()
        sf.header.dataOffset = r.read_int32()

        if sf.header.dataOffset > sf.header.fileSize:
            raise RuntimeError("Invalid dataOffset %d" % sf.header.dataOffset)

        if sf.header.metadataSize > sf.header.fileSize:
            raise RuntimeError("Invalid metadataSize %d" % sf.header.metadataSize)

        if sf.header.version >= 9:
            sf.header.endianness = r.read_int8()
            r.read(3) # reserved

        # newer formats use little-endian for the rest of the file
        if sf.header.version > 5:
            r.be = False

        # TODO: test more formats
        if sf.header.version != 15:
            raise NotImplementedError("Unsupported format version %d" % sf.header.version)

    def read_types(self, r, sf):
        sf.types = Munch()

        # older formats store the object data before the structure data
        if sf.header.version < 9:
            types_offset = sf.header.fileSize - sf.header.metadataSize + 1
            r.seek(types_offset)

        if sf.header.version > 6:
            sf.types.signature = r.read_cstring()
            sf.types.attributes = r.read_int32()

        if sf.header.version > 13:
            sf.types.embedded = r.read_int8() != 0

        sf.types.classes = {}

        num_classes = r.read_int32()
        for i in range(0, num_classes):
            bclass = Munch()

            class_id = r.read_int32()
            if class_id < 0:
                bclass.script_id = r.read_uuid()

            bclass.old_type_hash = r.read_uuid()

            if sf.types.embedded:
                bclass.type_tree = self.read_type_node(r, sf)

            if class_id in sf.types.classes:
                raise RuntimeError("Duplicate class ID %d" % class_id)

            sf.types.classes[class_id] = bclass

    def read_type_node(self, r, sf):
        fields = []
        num_fields = r.read_int32()
        string_table_len = r.read_int32()

        # read field list
        for i in range(num_fields):
            field = Munch()
            field.version = r.read_int16()
            field.tree_level = r.read_uint8()
            field.is_array = r.read_uint8() != 0
            field.type_offset = r.read_uint32()
            field.name_offset = r.read_uint32()
            field.size = r.read_int32()
            field.index = r.read_int32()
            field.meta_flag = r.read_int32()

            fields.append(field)

        # read local string table
        string_table_buf = r.read(string_table_len)
        string_table = self.streader.get(string_table_buf)

        # convert list to tree structure
        node_stack = []
        node_prev = None
        node_root = None

        for field in fields:
            # assign strings
            field.name = string_table[field.name_offset]
            field.type = string_table[field.type_offset]

            # don't need those offsets anymore
            del field.name_offset
            del field.type_offset

            # convert to node
            node = field
            node.children = []

            # set root node
            if not node_root:
                node_root = node_prev = node
                node_stack.append(node)
                continue

            # get tree level difference and move node up or down if required
            tree_level_diff = field.tree_level - node_prev.tree_level

            if tree_level_diff > 0:
                node_prev.children.append(node)
                node_stack.append(node_prev)
            elif tree_level_diff < 0:
                for i in range(-tree_level_diff):
                    node_stack.pop()

            node_stack[-1].children.append(node)
            node_prev = node

        return node_root

    def read_objects(self, r, sf):
        sf.objects = {}

        num_entries = r.read_int32()

        for i in range(0, num_entries):
            if sf.header.version > 13:
                r.align(4)

            path_id = r.read_int64()

            obj = Munch()
            obj.byte_start = r.read_uint32()
            obj.byte_size = r.read_uint32()
            obj.type_id = r.read_int32()
            obj.class_id = r.read_int16()

            if sf.header.version > 13:
                obj.script_type_index = r.read_int16()
            else:
                obj.is_destroyed = r.read_int16() != 0

            if sf.header.version > 14:
                obj.stripped = r.read_int8() != 0

            if path_id in sf.objects:
                raise RuntimeError("Duplicate path ID %d" % path_id)

            sf.objects[path_id] = obj

    def read_script_types(self, r, sf):
        sf.script_types = []

        num_entries = r.read_int32()

        for i in range(0, num_entries):
            r.align(4)

            script_type = Munch()
            script_type.serialized_file_index = r.read_int32()
            script_type.identifier_in_file = r.read_int64()

            sf.script_types.append(script_type)

    def read_externals(self, r, sf):
        sf.externals = []

        num_entries = r.read_int32()
        for i in range(0, num_entries):
            external = Munch()

            if sf.header.version > 5:
                external.asset_path = r.read_cstring()

            external.guid = r.read_uuid()
            external.type = r.read_int32()
            external.file_path = r.read_cstring()

            sf.externals.append(external)