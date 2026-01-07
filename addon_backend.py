import mitmproxy.http
import dy_pb2 as dy
import gzip
import json
import sys
import time
import brotli  # 需要 pip install brotli，如果没有也没关系，代码做了容错
from urllib.parse import parse_qs, urlparse

sys.stdout.reconfigure(encoding='utf-8')


class DouyinBackend:
    def __init__(self):
        self.discovered_rooms = set()
        self.last_clean_time = time.time()

    # === 1. 监听 HTTP (获取精准主播信息) ===
    def response(self, flow: mitmproxy.http.HTTPFlow):
        # 监听多种可能的进场接口
        if "webcast/room/enter_room" in flow.request.url:
            try:
                # 智能解压：处理 gzip, br 等多种压缩格式
                content = flow.response.content
                if flow.response.headers.get("content-encoding") == "br":
                    try:
                        content = brotli.decompress(content)
                    except:
                        pass
                elif flow.response.headers.get("content-encoding") == "gzip":
                    try:
                        content = gzip.decompress(content)
                    except:
                        pass

                json_str = content.decode('utf-8', errors='ignore')
                data = json.loads(json_str)

                # 兼容不同的数据结构
                room_data = data.get('data', {}).get('data', [])
                if not room_data:
                    # 有时候结构可能是 data.room
                    room_data = [data.get('data', {}).get('room', {})]

                if room_data:
                    room_info = room_data[0]
                    if not room_info: return

                    room_id = str(room_info.get('id_str', 'UNKNOWN'))
                    owner = room_info.get('owner', {})
                    nickname = owner.get('nickname', '未知主播')

                    # 提取 Short ID
                    display_id = owner.get('display_id', '')
                    short_id = owner.get('short_id', '')
                    real_id = display_id if display_id else str(short_id)

                    info_pack = {
                        "type": "anchor_info",
                        "room_id": room_id,
                        "user": nickname,
                        "douyin_id": real_id,
                        "content": "主播信息更新"
                    }
                    print(f"DY_DATA::{json.dumps(info_pack, ensure_ascii=False)}")
            except Exception as e:
                # print(f"DEBUG: 解析主播信息失败: {e}")
                pass

    # === 2. 监听 WebSocket (弹幕/礼物) ===
    def websocket_message(self, flow: mitmproxy.http.HTTPFlow):
        if "webcast" not in flow.request.url: return
        message = flow.websocket.messages[-1]
        if message.from_client: return

        try:
            query = parse_qs(urlparse(flow.request.url).query)
            room_id = query.get('room_id', ['UNKNOWN'])[0]
        except:
            room_id = "UNKNOWN"

        # 发送发现信号
        if room_id != "UNKNOWN" and room_id not in self.discovered_rooms:
            discovery_pack = {"type": "discovery", "room_id": room_id, "user": "获取中...", "content": "检测到直播流"}
            print(f"DY_DATA::{json.dumps(discovery_pack, ensure_ascii=False)}")
            self.discovered_rooms.add(room_id)

        if time.time() - self.last_clean_time > 600:
            self.discovered_rooms.clear();
            self.last_clean_time = time.time()

        try:
            push_frame = dy.PushFrame()
            push_frame.ParseFromString(message.content)
            payload = push_frame.payload
            try:
                payload = gzip.decompress(payload)
            except:
                pass

            response = dy.Response()
            response.ParseFromString(payload)

            for msg in response.messagesList:
                data_pack = {}

                # --- 弹幕 ---
                if msg.method == 'WebcastChatMessage':
                    try:
                        chat = dy.ChatMessage();
                        chat.ParseFromString(msg.payload)
                        data_pack = {"type": "chat", "room_id": room_id, "user": chat.user.nickName,
                                     "content": chat.content, "time": str(chat.common.createTime)}
                    except:
                        pass

                # --- 礼物 (容错版) ---
                elif msg.method == 'WebcastGiftMessage':
                    try:
                        gift = dy.GiftMessage();
                        gift.ParseFromString(msg.payload)
                        # 尽力获取字段，没有就给默认值
                        g_name = "未知礼物"
                        if hasattr(gift, 'gift') and gift.gift.name: g_name = gift.gift.name

                        g_user = "未知用户"
                        if hasattr(gift, 'user') and gift.user.nickName: g_user = gift.user.nickName

                        count = 1
                        if hasattr(gift, 'comboCount'): count = gift.comboCount

                        data_pack = {
                            "type": "gift",
                            "room_id": room_id,
                            "user": g_user,
                            "gift_name": g_name,
                            "count": count,
                            "time": str(gift.common.createTime)
                        }
                    except Exception as e:
                        # 哪怕解析烂了，也发一个包证明收到过礼物
                        data_pack = {"type": "gift", "room_id": room_id, "user": "解析错误", "gift_name": "未知",
                                     "count": 1, "time": ""}

                if data_pack:
                    try:
                        print(f"DY_DATA::{json.dumps(data_pack, ensure_ascii=False)}")
                    except:
                        pass

        except:
            pass


addons = [DouyinBackend()]

if __name__ == "__main__":
    from mitmproxy.tools.main import mitmdump

    params = ['-p', '8081', '-q', '-s', __file__]
    mitmdump(params)
