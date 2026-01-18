import asyncio
import json
import sys
import time
import gzip
# 引入 mitmproxy 核心组件，不再使用命令行的 mitmdump
from mitmproxy import options
from mitmproxy.tools.dump import DumpMaster
from mitmproxy.http import HTTPFlow
import dy_pb2 as dy
from urllib.parse import parse_qs, urlparse

# 尝试导入 brotli
try:
    import brotli
except ImportError:
    brotli = None

sys.stdout.reconfigure(encoding='utf-8')


class DouyinBackend:
    def __init__(self):
        self.discovered_rooms = set()
        self.last_clean_time = time.time()
        print(">>> DouyinBackend 插件已加载")

    # === 1. HTTP 响应 ===
    def response(self, flow: HTTPFlow):
        # 只要不是 enter_room，其他全部 stream 直通
        if "webcast/room/enter_room" not in flow.request.url:
            flow.response.stream = True
            return

        # 拦截进场信息
        flow.response.stream = False
        try:
            content = flow.response.content
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

            room_data = data.get('data', {}).get('data', [])
            if not room_data:
                room_data = [data.get('data', {}).get('room', {})]

            if room_data and room_data[0]:
                info = room_data[0]
                room_id = str(info.get('id_str', 'UNKNOWN'))
                owner = info.get('owner', {})
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
                sys.stdout.flush()  # 强制刷新缓冲区
        except:
            pass

    # === 2. WebSocket 监听 ===
    def websocket_message(self, flow: HTTPFlow):
        if "webcast" not in flow.request.url: return
        msg = flow.websocket.messages[-1]
        if msg.from_client: return

        try:
            query = parse_qs(urlparse(flow.request.url).query)
            room_id = query.get('room_id', ['UNKNOWN'])[0]
        except:
            room_id = "UNKNOWN"

        if room_id != "UNKNOWN" and room_id not in self.discovered_rooms:
            print(
                f"DY_DATA::{json.dumps({'type': 'discovery', 'room_id': room_id, 'user': '获取中...'}, ensure_ascii=False)}")
            sys.stdout.flush()
            self.discovered_rooms.add(room_id)

        if time.time() - self.last_clean_time > 600:
            self.discovered_rooms.clear();
            self.last_clean_time = time.time()

        try:
            push = dy.PushFrame()
            push.ParseFromString(msg.content)
            payload = push.payload
            try:
                payload = gzip.decompress(payload)
            except:
                pass

            resp = dy.Response()
            resp.ParseFromString(payload)

            for m in resp.messagesList:
                pack = {}
                if m.method == 'WebcastChatMessage':
                    try:
                        c = dy.ChatMessage();
                        c.ParseFromString(m.payload)
                        pack = {"type": "chat", "room_id": room_id, "user": c.user.nickName, "content": c.content,
                                "time": str(c.common.createTime)}
                    except:
                        pass
                elif m.method == 'WebcastGiftMessage':
                    try:
                        g = dy.GiftMessage();
                        g.ParseFromString(m.payload)
                        name = g.gift.name if hasattr(g, 'gift') else "未知礼物"
                        count = g.comboCount if hasattr(g, 'comboCount') else 1
                        pack = {"type": "gift", "room_id": room_id, "user": g.user.nickName, "gift_name": name,
                                "count": count, "time": str(g.common.createTime)}
                    except:
                        pass

                if pack:
                    try:
                        print(f"DY_DATA::{json.dumps(pack, ensure_ascii=False)}")
                        sys.stdout.flush()
                    except:
                        pass
        except:
            pass


# === 核心修改：使用 asyncio 直接启动 DumpMaster ===
# === 核心修改：修正参数拼写错误 ===
async def start_proxy():
    print(">>> 正在启动内置代理服务 (Port: 8081)...")

    # 1. 创建配置
    opts = options.Options(listen_host='127.0.0.1', listen_port=8081)

    # 2. 创建 Master
    # 注意：参数名是 with_dumper，不是 with_dump
    master = DumpMaster(opts, with_termlog=False, with_dumper=False)

    # 3. 设置选项 (必须在创建 master 之后)
    master.options.ssl_insecure = True
    master.options.stream_large_bodies = '1m'
    master.options.ignore_hosts = ['^(?!.*webcast).*']

    # 4. 加载插件
    master.addons.add(DouyinBackend())

    try:
        await master.run()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    # Windows下 asyncio 策略调整
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    asyncio.run(start_proxy())