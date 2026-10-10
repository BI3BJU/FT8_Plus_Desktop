# ft8_crc.py - CRC8 工具
def _crc8_table(poly=0x07):
    table = []
    for i in range(256):
        crc = i
        for _bit in range(8):
            if crc & 0x80:
                crc = (crc << 1) ^ poly
            else:
                crc <<= 1
            crc &= 0xFF
        table.append(crc)
    return table


_CRC8_TABLE = _crc8_table()


def crc8(data, poly=0x07, init=0x00):
    crc = init
    for byte in data:
        crc = _CRC8_TABLE[(crc ^ byte) & 0xFF]
    return crc
