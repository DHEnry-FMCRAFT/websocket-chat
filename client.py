import asyncio
import websockets
import json
import threading
import sys
import random
import string
import hashlib
from datetime import datetime

# 调试模式设置：1-使用默认服务器地址，0-需要手动输入服务器地址
DEBUG = 0

def hash_password(password):
    """对密码进行哈希处理"""
    return hashlib.sha256(password.encode('utf-8')).hexdigest()

class ChatClient:
    def __init__(self, server_address):
        self.username = None
        self.websocket = None
        self.running = False
        self.current_channel = "public"  # 默认频道
        self.loop = None
        self.server_address = server_address
        self.first_input = True  # 标记是否是第一次输入
        self.joined = False  # 标记是否已加入频道
        self.is_admin = False  # 是否为管理员
        self.waiting_for_password = False  # 是否正在等待输入密码

    async def connect(self):
        """连接到WebSocket服务器"""
        self.running = True
        self.loop = asyncio.get_running_loop()
        
        try:
            async with websockets.connect(f"ws://{self.server_address}") as websocket:
                self.websocket = websocket
                
                # 启动消息接收协程
                receive_task = asyncio.create_task(self.receive_messages())
                
                # 启动输入线程
                input_thread = threading.Thread(target=self.input_loop, daemon=True)
                input_thread.start()
                
                # 等待接收任务完成
                await receive_task
                
        except ConnectionRefusedError:
            print(f"无法连接到服务器 {self.server_address}，请确保服务器已启动")
        except Exception as e:
            print(f"连接错误: {e}")
        finally:
            self.running = False

    async def receive_messages(self):
        """接收并显示服务器发送的消息"""
        while self.running and self.websocket:
            try:
                message = await self.websocket.recv()
                data = json.loads(message)
                
                # 确保消息包含必要的字段
                required_fields = ['type', 'channel', 'time']
                for field in required_fields:
                    if field not in data:
                        data[field] = '' if field != 'time' else datetime.now().strftime("%H:%M:%S")
                
                # 清除输入提示
                sys.stdout.write("\033[K")  # 清除当前行
                
                # 提取频道信息
                channel = data['channel']
                
                # 处理管理员认证相关消息
                if data['type'] == 'require_password':
                    self.waiting_for_password = True
                    print(f"\033[93m[{channel}] {data['message']}\033[0m")
                    print(f"\033[93m请输入密码:\033[0m ", end="", flush=True)
                    continue
                
                # 处理管理员登录成功和命令提示
                if data['type'] == 'system' and 'admin_commands' in data:
                    self.is_admin = True
                    print(f"\033[90m[{channel}] [{data['time']}] 系统消息: {data['message']}\033[0m")
                    print("\033[93m管理员可用命令:\033[0m")
                    for cmd in data['admin_commands']:
                        print(f"\033[93m  {cmd}\033[0m")
                
                # 根据消息类型显示不同格式
                elif data['type'] == 'system':
                    print(f"\033[90m[{channel}] [{data['time']}] 系统消息: {data['message']}\033[0m")
                    
                    # 如果是被踢出或清退，允许用户重新选择频道
                    if any(msg in data['message'] for msg in ['已从频道被踢出', '该频道已被清退', '该频道被封禁']):
                        self.current_channel = "public"  # 重置为默认频道
                        self.joined = False
                        print(f"\033[90m系统消息: 您可以使用 ::choose [频道ID] 命令重新加入其他频道\033[0m")
                
                elif data['type'] == 'message':
                    username = data.get('username', '未知用户')
                    msg_content = data.get('message', '')
                    print(f"\033[94m[{channel}] [{data['time']}] {username}:\033[0m {msg_content}")
                elif data['type'] == 'error':
                    print(f"\033[91m[{channel}] 错误: {data['message']}\033[0m")
                elif data['type'] == 'user_list':
                    print(f"\033[90m[{channel}] [{data['time']}] 系统消息: {data['message']}\033[0m")
                    print(f"\033[96m  {data['users']}\033[0m")
                
                # 更新当前频道
                if data['type'] == 'system' and (data['message'].startswith('已切换到频道') or 
                                               data['message'].startswith('成功加入频道')):
                    self.current_channel = channel
                    self.joined = True
                
                # 显示输入提示
                if self.waiting_for_password:
                    print(f"\033[93m请输入密码:\033[0m ", end="", flush=True)
                else:
                    print(f"\033[92m[{self.current_channel}] 你:\033[0m ", end="", flush=True)
                
            except websockets.exceptions.ConnectionClosed:
                print("\n与服务器的连接已关闭")
                break
            except json.JSONDecodeError:
                print("\n收到无效格式的消息")
            except Exception as e:
                print(f"\n接收消息错误: {e}")

    def generate_random_username(self):
        """生成5位随机字母数字组合的用户名"""
        letters_and_digits = string.ascii_letters + string.digits
        return ''.join(random.choice(letters_and_digits) for _ in range(5))

    def input_loop(self):
        """处理用户输入并发送消息"""
        asyncio.set_event_loop(asyncio.new_event_loop())
        loop = asyncio.get_event_loop()
        
        # 显示初始提示信息
        print("\n===== 聊天提示 =====")
        print("可直接发送消息（系统会自动分配用户名和频道）")
        print("公共命令:")
        print("::login [用户名] - 设置你的用户名")
        print("::choose [频道ID] - 选择或切换聊天频道")
        print("::list [频道id] - 查看指定频道在线用户")
        print("exit 或 quit - 退出聊天")
        
        # 初始只显示公共命令，管理员命令在登录后显示
        print("======================")
        print(f"\033[92m[{self.current_channel}] 你:\033[0m ", end="", flush=True)
        
        while self.running:
            try:
                message = input()
                
                if message.lower() in ['exit', 'quit']:
                    self.running = False
                    if self.websocket:
                        loop.run_until_complete(
                            self.websocket.send(json.dumps({'action': 'leave'}))
                        )
                        loop.run_until_complete(self.websocket.close())
                    print("已退出聊天")
                    break
                
                # 处理密码输入
                if self.waiting_for_password:
                    password = message.strip()
                    if password:
                        password_hash = hash_password(password)
                        
                        loop.run_until_complete(
                            self.websocket.send(json.dumps({
                                'action': 'login',
                                'username': self.username,
                                'channel': self.current_channel,
                                'password_hash': password_hash
                            }))
                        )
                        self.waiting_for_password = False
                    
                    print(f"\033[92m[{self.current_channel}] 你:\033[0m ", end="", flush=True)
                    continue
                
                # 处理查看频道用户命令
                if message.startswith('::list '):
                    parts = message.split()
                    if len(parts) < 2:
                        print(f"\033[91m错误: 命令格式应为 ::list [频道id]\033[0m")
                        print(f"\033[92m[{self.current_channel}] 你:\033[0m ", end="", flush=True)
                        continue
                        
                    channel_id = parts[1]
                    loop.run_until_complete(
                        self.websocket.send(json.dumps({
                            'action': 'list_command',
                            'channel_id': channel_id
                        }))
                    )
                    print(f"\033[92m[{self.current_channel}] 你:\033[0m ", end="", flush=True)
                    self.first_input = False
                    continue
                
                # 处理管理员命令
                if self.is_admin:
                    # 处理查看全服用户命令
                    if message == '::lists':
                        loop.run_until_complete(
                            self.websocket.send(json.dumps({
                                'action': 'admin_command',
                                'command': message
                            }))
                        )
                        print(f"\033[92m[{self.current_channel}] 你:\033[0m ", end="", flush=True)
                        self.first_input = False
                        continue
                    
                    # 处理私信命令
                    if message.startswith('::say '):
                        loop.run_until_complete(
                            self.websocket.send(json.dumps({
                                'action': 'admin_command',
                                'command': message
                            }))
                        )
                        print(f"\033[92m[{self.current_channel}] 你:\033[0m ", end="", flush=True)
                        self.first_input = False
                        continue
                    
                    # 处理其他管理员命令
                    if message.startswith(('::kicks', '::kick', '::closes', '::close')):
                        loop.run_until_complete(
                            self.websocket.send(json.dumps({
                                'action': 'admin_command',
                                'command': message
                            }))
                        )
                        print(f"\033[92m[{self.current_channel}] 你:\033[0m ", end="", flush=True)
                        self.first_input = False
                        continue
                else:
                    # 非管理员尝试使用管理员命令
                    if message.startswith(('::lists', '::say', '::kicks', '::kick', '::closes', '::close')):
                        print(f"\033[91m错误: 你没有权限执行此命令\033[0m")
                        print(f"\033[92m[{self.current_channel}] 你:\033[0m ", end="", flush=True)
                        continue
                
                # 处理频道切换命令
                if message.startswith('::choose '):
                    new_channel = message[len('::choose '):].strip()
                    if new_channel and new_channel != self.current_channel:
                        if not self.username:
                            self.username = self.generate_random_username()
                            print(f"\033[90m系统消息: 未设置用户名，已自动分配: {self.username}\033[0m")
                        
                        loop.run_until_complete(
                            self.websocket.send(json.dumps({
                                'action': 'choose',
                                'username': self.username,
                                'old_channel': self.current_channel,
                                'new_channel': new_channel
                            }))
                        )
                    print(f"\033[92m[{self.current_channel}] 你:\033[0m ", end="", flush=True)
                    self.first_input = False
                    continue
                
                # 处理登录命令
                if message.startswith('::login '):
                    new_username = message[len('::login '):].strip()
                    if new_username and new_username != self.username:
                        self.username = new_username
                        
                        # 发送登录信息
                        login_data = {
                            'action': 'login',
                            'username': self.username,
                            'channel': self.current_channel
                        }
                        
                        loop.run_until_complete(
                            self.websocket.send(json.dumps(login_data))
                        )
                        print(f"\033[90m系统消息: 已设置用户名为: {self.username}\033[0m")
                    
                    print(f"\033[92m[{self.current_channel}] 你:\033[0m ", end="", flush=True)
                    self.first_input = False
                    continue
                
                # 处理普通消息
                message = message.strip()
                if message:
                    # 第一次输入且没有用户名，自动生成
                    if self.first_input and not self.username:
                        self.username = self.generate_random_username()
                        print(f"\033[90m系统消息: 未设置用户名，已自动分配: {self.username}\033[0m")
                        
                        # 自动加入默认频道
                        if not self.joined:
                            print(f"\033[90m系统消息: 未选择频道，已自动加入默认频道: {self.current_channel}\033[0m")
                            loop.run_until_complete(
                                self.websocket.send(json.dumps({
                                    'action': 'login',
                                    'username': self.username,
                                    'channel': self.current_channel
                                }))
                            )
                            self.joined = True
                    
                    # 发送消息
                    if self.joined and self.websocket:
                        loop.run_until_complete(
                            self.websocket.send(json.dumps({
                                'action': 'message',
                                'message': message
                            }))
                        )
                    elif self.websocket:
                        self.joined = True
                        loop.run_until_complete(
                            self.websocket.send(json.dumps({
                                'action': 'login',
                                'username': self.username,
                                'channel': self.current_channel
                            }))
                        )
                        loop.run_until_complete(asyncio.sleep(0.1))
                        loop.run_until_complete(
                            self.websocket.send(json.dumps({
                                'action': 'message',
                                'message': message
                            }))
                        )
                
                # 更新输入提示
                print(f"\033[92m[{self.current_channel}] 你:\033[0m ", end="", flush=True)
                self.first_input = False
                
            except EOFError:
                break
            except Exception as e:
                print(f"输入错误: {e}")
                print(f"\033[92m[{self.current_channel}] 你:\033[0m ", end="", flush=True)
        loop.close()

async def main():
    print("=== WebSocket 聊天客户端 ===")
    
    if DEBUG:
        server_address = "localhost:8765"
        print(f"DEBUG模式启用，使用默认服务器地址: {server_address}")
    else:
        server_address = input("请输入服务器地址(格式: ip:端口): ")
        if ":" not in server_address:
            print("地址格式不正确，应使用 ip:端口 格式")
            return
    
    client = ChatClient(server_address)
    await client.connect()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n客户端已关闭")
    