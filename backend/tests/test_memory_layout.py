"""目录重构兼容性：读取重构前生成的检查点字节，并确认新写入使用新模块路径。"""

import base64

from app.agent.memory.comment_memory import CommentMemory
from app.agent.memory.order_memory import OrderMemory
from app.agent.memory.persistence import create_memory_serializer


def test_legacy_checkpoint_survives_module_move():
    # 此夹具由移动前的类序列化生成，只有合成测试数据，不含客户历史。
    encoded = "gqxvcmRlcl9tZW1vcnnHpQWUtmFwcC5hZ2VudC5vcmRlcl9tZW1vcnmrT3JkZXJNZW1vcnmGp3ZlcnNpb24BpXN0YWdlrWNvbGxlY3RfaXNzdWWqY2FuZGlkYXRlc5Coc2VsZWN0ZWSCpGNvZGWnTU8tdGVzdKxwcm9kdWN0X25hbWWs5rWL6K+V6K6+5aSHqXJlZmVyZW5jZaClaXNzdWWgs21vZGVsX3ZhbGlkYXRlX2pzb26uY29tbWVudF9tZW1vcnnHeQWUuGFwcC5hZ2VudC5jb21tZW50X21lbW9yea1Db21tZW50TWVtb3J5hKZhY3RpdmXDqXJlZmVyZW5jZaCnY29udGVudKzmtYvor5XooaXlhYWqY2FuZGlkYXRlc5GnVEstdGVzdLNtb2RlbF92YWxpZGF0ZV9qc29u"
    serde = create_memory_serializer()
    restored = serde.loads_typed(("msgpack", base64.b64decode(encoded)))
    assert isinstance(restored["order_memory"], OrderMemory)
    assert restored["order_memory"].selected.code == "MO-test"
    assert isinstance(restored["comment_memory"], CommentMemory)
    assert restored["comment_memory"].content == "测试补充"
    # 兼容只影响读取；新的检查点不再产生旧模块名。
    kind, payload = serde.dumps_typed(restored)
    assert b"app.agent.memory.order_memory" in payload
    assert b"app.agent.memory.comment_memory" in payload
    assert serde.loads_typed((kind, payload)) == restored
