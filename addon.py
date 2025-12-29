import mitmproxy.http
from mitmproxy import ctx
import dy_pb2 as dy  # 必须要有 dy_pb2.py 文件
import gzip
import sys


class DouyinDecoder:
    def __init__(self):
        print(">>> 翻译机已就位：正在监听并解码弹幕...")

    def websocket_message(self, flow: mitmproxy.http.HTTPFlow):
        if "webcast/im/push" not in flow.request.url:
            return

        message = flow.websocket.messages[-1]
        if message.from_client:
            return

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

            if response.messagesList:
                # 这里的 print 可以注释掉，不然控制台太乱
                # print(f"\n>>> 收到数据包，内含 {len(response.messagesList)} 条消息:")

                for msg in response.messagesList:
                    method = msg.method

                    try:
                        # 1. 聊天弹幕 (这是你最想要的)
                        if method == 'WebcastChatMessage':
                            chat = dy.ChatMessage()
                            chat.ParseFromString(msg.payload)
                            print(f"[弹幕] {chat.user.nickName}: {chat.content}")

                        # 2. 礼物消息 (这也是你想要的)
                        elif method == 'WebcastGiftMessage':
                            gift = dy.GiftMessage()
                            gift.ParseFromString(msg.payload)
                            print(f"[礼物] {gift.user.nickName} 送出了 {gift.gift.name}")

                        # 3. 其他消息 (点赞、进场、关注等)
                        # 直接 pass 跳过，不处理，也就不会报错了
                        else:
                            pass

                    except Exception as e:
                        # 只有真的弹幕解析出错才打印，避免刷屏
                        pass

        except Exception as e:
            pass

addons = [
    DouyinDecoder()
]

if __name__ == '__main__':
    from mitmproxy.tools.main import mitmdump

    # 启用 quiet 模式(-q)，减少不必要的系统日志，只看我们的 print
    mitmdump(['-p', '8080', '-q', '-s', __file__])