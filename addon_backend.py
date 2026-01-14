
import mitmproxy.http
import dy_pb2 as dy
import gzip
import json
import sys
import time
from urllib.parse import parse_qs, urlparse

# 尝试导入 brotli，没有就忽略（抖音有时用br压缩）
try:
    import brotli
except ImportError:
    brotli = None

sys.stdout.reconfigure(encoding='utf-8')


class DouyinBackend:
    def __init__(self):
        self.discovered_rooms = set()
        self.last_clean_time = time.time()

    # === 1. HTTP 响应：极简白名单模式 ===
    def response(self, flow: mitmproxy.http.HTTPFlow):
        # 默认：开启流模式（Stream），让数据直接通过，不缓存，不解析
        # 这能解决 99% 的视频卡顿问题
        flow.response.stream = True

        url = flow.request.url

        # 特例：如果是“进入房间”接口，我们需要数据，所以关闭流模式，进行拦截
        if "webcast/room/enter_room" in url:
            flow.response.stream = False

            try:
                content = flow.response.content
                # 处理压缩
                encoding = flow.response.headers.get("content-encoding", "")
                if encoding == "br" and brotli:
                    try:
                        content = brotli.decompress(content)
                    except:
                        pass
                elif encoding == "gzip":
                    try:
                        content = gzip.decompress(content)
                    except:
                        pass

                json_str = content.decode('utf-8', errors='ignore')
                data = json.loads(json_str)

                # 兼容两种数据结构
                room_data = data.get('data', {}).get('data', [])
                if not room_data:
                    room_data = [data.get('data', {}).get('room', {})]

                if room_data and room_data[0]:
                    room_info = room_data[0]
                    room_id = str(room_info.get('id_str', 'UNKNOWN'))
                    owner = room_info.get('owner', {})
                    nickname = owner.get('nickname', '未知主播')

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
            except:
                pass

    # === 2. WebSocket 监听 (弹幕/礼物) ===
    # WebSocket 不受 HTTP stream 影响，它是独立协议，这里逻辑不变
    def websocket_message(self, flow: mitmproxy.http.HTTPFlow):
        if "webcast" not in flow.request.url: return

        message = flow.websocket.messages[-1]
        if message.from_client: return

        try:
            query = parse_qs(urlparse(flow.request.url).query)
            room_id = query.get('room_id', ['UNKNOWN'])[0]
        except:
            room_id = "UNKNOWN"

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
                if msg.method == 'WebcastChatMessage':
                    try:
                        chat = dy.ChatMessage();
                        chat.ParseFromString(msg.payload)
                        data_pack = {"type": "chat", "room_id": room_id, "user": chat.user.nickName,
                                     "content": chat.content, "time": str(chat.common.createTime)}
                    except:
                        pass
                elif msg.method == 'WebcastGiftMessage':
                    try:
                        gift = dy.GiftMessage();
                        gift.ParseFromString(msg.payload)
                        g_name = "未知礼物"
                        if hasattr(gift, 'gift') and gift.gift.name: g_name = gift.gift.name
                        count = 1
                        if hasattr(gift, 'comboCount'): count = gift.comboCount
                        data_pack = {"type": "gift", "room_id": room_id, "user": gift.user.nickName,
                                     "gift_name": g_name, "count": count, "time": str(gift.common.createTime)}
                    except:
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

    # 强制使用 8081
    params = ['-p', '8081', '-q', '-s', __file__]
    mitmdump(params)

