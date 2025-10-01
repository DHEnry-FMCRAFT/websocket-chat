import asyncio
import websockets
import json
from datetime import datetime
from collections import defaultdict
import hashlib

ADMIN_PASSWORD_HASH = ""

# 允许的频道列表
ALLOWED_CHANNELS = ["public","1","2","3"]

# 数据结构：{频道ID: {用户名: websocket连接}}
channels = defaultdict(dict)

# 反向映射：{websocket连接: (用户名, 频道, 是否管理员)}
connection_map = {}

async def broadcast(channel_id, message_data):
    """向指定频道的所有在线用户广播消息"""
    if channel_id not in channels:
        return
    
    message_data["time"] = datetime.now().strftime("%H:%M:%S")
    message_data["channel"] = channel_id
    message_json = json.dumps(message_data)
    
    for websocket in list(channels[channel_id].values()):  # 使用列表避免迭代中修改
        try:
            await websocket.send(message_json)
        except websockets.exceptions.ConnectionClosed:
            # 移除已关闭的连接
            if websocket in connection_map:
                username, channel, is_admin = connection_map[websocket]
                if username in channels[channel]:
                    del channels[channel][username]
                del connection_map[websocket]

async def send_private_message(websocket, message_data):
    """向指定用户发送私信"""
    message_data["time"] = datetime.now().strftime("%H:%M:%S")
    message_json = json.dumps(message_data)
    
    try:
        await websocket.send(message_json)
    except websockets.exceptions.ConnectionClosed:
        # 移除已关闭的连接
        if websocket in connection_map:
            username, channel, is_admin = connection_map[websocket]
            if username in channels[channel]:
                del channels[channel][username]
            del connection_map[websocket]

async def handle_admin_command(websocket, command, admin_username):
    """处理管理员命令"""
    parts = command.strip().split(maxsplit=3)
    if not parts or parts[0] not in ['::kicks', '::kick', '::closes', '::close', '::lists', '::say']:
        await websocket.send(json.dumps({
            "type": "error",
            "channel": connection_map[websocket][1],
            "message": "无效的管理员命令"
        }))
        return
    
    cmd = parts[0]
    current_username, current_channel, _ = connection_map[websocket]
    
    # 处理查看全服用户命令
    if cmd == '::lists':
        all_users = []
        for channel, users in channels.items():
            for user in users:
                all_users.append(f"{user}@{channel}")
        
        if all_users:
            user_list = "    ".join(all_users)  # 4个空格分隔
            await websocket.send(json.dumps({
                "type": "user_list",
                "channel": current_channel,
                "message": f"全服在线用户 ({len(all_users)}):",
                "users": user_list
            }))
        else:
            await websocket.send(json.dumps({
                "type": "system",
                "channel": current_channel,
                "message": "当前没有在线用户"
            }))
        return
    
    # 处理私信命令
    if cmd == '::say':
        if len(parts) < 4:
            await websocket.send(json.dumps({
                "type": "error",
                "channel": current_channel,
                "message": '命令格式应为 ::say [频道id] [用户名] [消息，用"包裹"]'
            }))
            return
            
        target_channel = parts[1]
        target_user = parts[2]
        message_content = parts[3]
        
        # 移除消息可能的引号
        if message_content.startswith('"') and message_content.endswith('"'):
            message_content = message_content[1:-1]
        
        # 检查目标用户是否存在
        if target_channel not in channels or target_user not in channels[target_channel]:
            await websocket.send(json.dumps({
                "type": "error",
                "channel": current_channel,
                "message": f"用户 {target_user} 不在频道 {target_channel} 中"
            }))
            return
            
        # 获取目标用户的连接
        target_websocket = channels[target_channel][target_user]
        
        # 发送私信给目标用户
        await send_private_message(target_websocket, {
            "type": "message",
            "channel": target_channel,
            "username": f"管理员 {current_username}",
            "message": f"[私信] {message_content}"
        })
        
        # 向管理员确认消息已发送
        await websocket.send(json.dumps({
            "type": "system",
            "channel": current_channel,
            "message": f"已向频道 {target_channel} 的用户 {target_user} 发送私信"
        }))
        return
    
    # 验证频道是否存在
    if len(parts) < 2:
        await websocket.send(json.dumps({
            "type": "error",
            "channel": current_channel,
            "message": "请指定频道ID"
        }))
        return
        
    channel_id = parts[1]
    if channel_id not in channels and cmd not in ['::close', '::closes']:
        await websocket.send(json.dumps({
            "type": "error",
            "channel": current_channel,
            "message": f"频道 '{channel_id}' 不存在"
        }))
        return
    
    # 验证是否提供了理由
    if len(parts) < 3:
        await websocket.send(json.dumps({
            "type": "error",
            "channel": current_channel,
            "message": "请提供操作理由"
        }))
        return
    
    reason = ' '.join(parts[2:])
    
    # 处理踢出单个用户命令
    if cmd == '::kicks':
        if len(parts) < 3:
            await websocket.send(json.dumps({
                "type": "error",
                "channel": current_channel,
                "message": "命令格式应为 ::kicks [频道id] [用户名] [理由]"
            }))
            return
            
        username = parts[2]
        reason = ' '.join(parts[3:]) if len(parts) > 3 else "无理由"
        
        if username not in channels[channel_id]:
            await websocket.send(json.dumps({
                "type": "error",
                "channel": current_channel,
                "message": f"用户 '{username}' 不在频道 '{channel_id}' 中"
            }))
            return
            
        # 不能踢自己
        if username == current_username:
            await websocket.send(json.dumps({
                "type": "error",
                "channel": current_channel,
                "message": "不能踢自己"
            }))
            return
            
        # 获取用户连接
        user_websocket = channels[channel_id][username]
        
        # 从频道移除用户
        del channels[channel_id][username]
        
        # 更新连接映射
        if user_websocket in connection_map:
            connection_map[user_websocket] = (username, "public", False)
        
        # 通知被踢用户
        await user_websocket.send(json.dumps({
            "type": "system",
            "channel": channel_id,
            "message": f"您已从频道被踢出，{reason}"
        }))
        
        # 广播用户被踢消息
        await broadcast(channel_id, {
            "type": "system",
            "message": f"用户 {username} 已被管理员踢出频道，{reason}"
        })
        
        # 通知管理员操作成功
        await websocket.send(json.dumps({
            "type": "system",
            "channel": current_channel,
            "message": f"已将用户 {username} 从频道 {channel_id} 踢出"
        }))
        return
    
    # 处理清退频道所有用户命令
    if cmd == '::kick':
        if not channels[channel_id]:
            await websocket.send(json.dumps({
                "type": "error",
                "channel": current_channel,
                "message": f"频道 '{channel_id}' 中没有用户"
            }))
            return
            
        # 保存要踢出的用户
        users_to_kick = list(channels[channel_id].items())
        kicked_users = [user for user, _ in users_to_kick if user != current_username]
        
        if not kicked_users:
            await websocket.send(json.dumps({
                "type": "system",
                "channel": current_channel,
                "message": f"频道 '{channel_id}' 中只有您自己，无需清退"
            }))
            return
            
        # 踢出所有非管理员用户
        for username, websocket in users_to_kick:
            if username != current_username:  # 保留管理员
                del channels[channel_id][username]
                
                # 更新连接映射
                if websocket in connection_map:
                    connection_map[websocket] = (username, "public", False)
                
                # 通知被踢用户
                await websocket.send(json.dumps({
                    "type": "system",
                    "channel": channel_id,
                    "message": f"该频道已被清退，{reason}"
                }))
        
        # 广播清退消息
        await broadcast(channel_id, {
            "type": "system",
            "message": f"频道已被管理员清退，{reason}"
        })
        
        # 通知管理员操作成功
        await websocket.send(json.dumps({
            "type": "system",
            "channel": current_channel,
            "message": f"已清退频道 '{channel_id}' 中的 {len(kicked_users)} 名用户"
        }))
        return
    
    # 处理断开单个用户连接命令
    if cmd == '::closes':
        if len(parts) < 3:
            await websocket.send(json.dumps({
                "type": "error",
                "channel": current_channel,
                "message": "命令格式应为 ::closes [频道id] [用户名] [理由]"
            }))
            return
            
        username = parts[2]
        reason = ' '.join(parts[3:]) if len(parts) > 3 else "无理由"
        
        if username not in channels[channel_id]:
            await websocket.send(json.dumps({
                "type": "error",
                "channel": current_channel,
                "message": f"用户 '{username}' 不在频道 '{channel_id}' 中"
            }))
            return
            
        # 不能断开自己的连接
        if username == current_username:
            await websocket.send(json.dumps({
                "type": "error",
                "channel": current_channel,
                "message": "不能断开自己的连接"
            }))
            return
            
        # 获取用户连接
        user_websocket = channels[channel_id][username]
        
        # 从频道移除用户
        del channels[channel_id][username]
        
        # 从连接映射移除
        if user_websocket in connection_map:
            del connection_map[user_websocket]
        
        # 通知用户连接将被断开
        try:
            await user_websocket.send(json.dumps({
                "type": "system",
                "channel": channel_id,
                "message": f"您的连接已被主动断开，{reason}"
            }))
            # 等待消息发送
            await asyncio.sleep(0.1)
        except:
            pass
        
        # 关闭用户连接
        await user_websocket.close()
        
        # 广播用户被断开连接消息
        await broadcast(channel_id, {
            "type": "system",
            "message": f"用户 {username} 已被管理员断开连接，{reason}"
        })
        
        # 通知管理员操作成功
        await websocket.send(json.dumps({
            "type": "system",
            "channel": current_channel,
            "message": f"已断开用户 {username} 的连接"
        }))
        return
    
    # 处理关闭频道命令
    if cmd == '::close':
        if not channels[channel_id]:
            await websocket.send(json.dumps({
                "type": "error",
                "channel": current_channel,
                "message": f"频道 '{channel_id}' 中没有用户"
            }))
            return
            
        # 保存要断开连接的用户
        users_to_disconnect = list(channels[channel_id].items())
        disconnected_users = [user for user, _ in users_to_disconnect if user != current_username]
        
        # 断开所有非管理员用户的连接
        for username, websocket in users_to_disconnect:
            if username != current_username:  # 保留管理员
                # 从频道移除用户
                del channels[channel_id][username]
                
                # 从连接映射移除
                if websocket in connection_map:
                    del connection_map[websocket]
                
                # 通知用户连接将被断开
                try:
                    await websocket.send(json.dumps({
                        "type": "system",
                        "channel": channel_id,
                        "message": f"该频道被封禁，{reason}"
                    }))
                    # 等待消息发送
                    await asyncio.sleep(0.1)
                except:
                    pass
                
                # 关闭用户连接
                await websocket.close()
        
        # 通知管理员操作成功
        await websocket.send(json.dumps({
            "type": "system",
            "channel": current_channel,
            "message": f"已关闭频道 '{channel_id}'，共断开 {len(disconnected_users)} 名用户的连接"
        }))
        return

async def handle_client(websocket):
    """处理单个客户端的连接逻辑"""
    current_username = None
    current_channel = None
    is_admin = False
    login_completed = False  # 跟踪登录流程是否完成
    
    try:
        while True:
            # 接收客户端消息
            message = await websocket.recv()
            data = json.loads(message)
            
            # 处理登录请求
            if data.get('action') == 'login':
                username = data.get('username')
                channel = data.get('channel')
                
                if not username or not channel:
                    await websocket.send(json.dumps({
                        "type": "error",
                        "channel": channel or "unknown",
                        "message": "用户名和频道不能为空"
                    }))
                    continue
                
                # 验证频道是否允许
                if channel not in ALLOWED_CHANNELS:
                    await websocket.send(json.dumps({
                        "type": "error",
                        "channel": channel,
                        "message": f"频道 '{channel}' 不被允许"
                    }))
                    continue
                
                # 处理管理员登录
                admin_login = username.lower() == 'administrator'
                if admin_login:
                    # 检查是否提供了密码哈希
                    password_hash = data.get('password_hash')
                    if not password_hash:
                        # 请求密码
                        await websocket.send(json.dumps({
                            "type": "require_password",
                            "channel": channel,
                            "message": "管理员登录需要密码"
                        }))
                        continue
                    
                    # 验证密码哈希
                    if password_hash != ADMIN_PASSWORD_HASH:
                        await websocket.send(json.dumps({
                            "type": "error",
                            "channel": channel,
                            "message": "密码错误，无法登录管理员账号"
                        }))
                        continue
                    
                    # 密码验证成功，设置为管理员
                    is_admin = True
                
                # 用户名存在性检查逻辑
                username_exists = False
                if channel in channels and username in channels[channel]:
                    # 检查该用户名是否属于当前连接
                    existing_connection = channels[channel][username]
                    if existing_connection != websocket:
                        username_exists = True
                
                if username_exists:
                    await websocket.send(json.dumps({
                        "type": "error",
                        "channel": channel,
                        "message": f"用户名 '{username}' 在频道 '{channel}' 中已存在，请更换用户名"
                    }))
                    continue
                
                # 如果用户之前在其他频道，先移除
                if current_username and current_channel and current_username in channels[current_channel]:
                    del channels[current_channel][current_username]
                    await broadcast(current_channel, {
                        "type": "system",
                        "message": f"{current_username} 离开了频道"
                    })
                
                # 更新当前用户信息
                current_username = username
                current_channel = channel
                
                # 添加用户到频道
                channels[current_channel][current_username] = websocket
                
                # 更新连接映射
                connection_map[websocket] = (current_username, current_channel, is_admin)
                
                # 标记登录完成
                login_completed = True
                
                # 发送登录成功消息
                login_msg = {
                    "type": "system",
                    "channel": current_channel,
                    "message": f"成功登录，用户名: {current_username}"
                }
                
                # 如果是管理员，添加管理员命令列表
                if is_admin:
                    login_msg["admin_commands"] = [
                        "::kicks [频道id] [用户名] [理由] - 踢出指定频道中的指定用户",
                        "::kick [频道id] [理由] - 清退指定频道中的所有用户",
                        "::closes [频道id] [用户名] [理由] - 断开指定用户的连接",
                        "::close [频道id] [理由] - 关闭频道并断开所有用户连接",
                        "::lists - 查看全服在线用户名",
                        f'::say [频道id] [用户名] [消息，用"包裹"] - 向指定用户发送私信'
                    ]
                
                await websocket.send(json.dumps(login_msg))
                
                # 广播用户加入消息
                await broadcast(current_channel, {
                    "type": "system",
                    "message": f"{current_username} 加入了频道"
                })
            
            # 处理频道选择请求
            elif data.get('action') == 'choose':
                if not current_username:
                    # 获取用户名（可能是自动生成的）
                    current_username = data.get('username')
                    if not current_username:
                        await websocket.send(json.dumps({
                            "type": "error",
                            "channel": data.get('new_channel', "unknown"),
                            "message": "请先登录设置用户名"
                        }))
                        continue
                    
                new_channel = data.get('new_channel')
                
                if not new_channel:
                    await websocket.send(json.dumps({
                        "type": "error",
                        "channel": current_channel or "unknown",
                        "message": "频道ID不能为空"
                    }))
                    continue
                
                # 验证新频道是否允许
                if new_channel not in ALLOWED_CHANNELS:
                    await websocket.send(json.dumps({
                        "type": "error",
                        "channel": new_channel,
                        "message": f"频道 '{new_channel}' 不被允许"
                    }))
                    continue
                
                # 验证用户名在新频道是否已存在
                if new_channel != current_channel and current_username in channels[new_channel]:
                    await websocket.send(json.dumps({
                        "type": "error",
                        "channel": new_channel,
                        "message": f"用户名 '{current_username}' 在频道 '{new_channel}' 中已存在，请更换用户名"
                    }))
                    continue
                
                # 从旧频道移除用户
                if current_channel and current_username in channels[current_channel]:
                    del channels[current_channel][current_username]
                    await broadcast(current_channel, {
                        "type": "system",
                        "message": f"{current_username} 离开了频道"
                    })
                
                # 更新当前频道
                current_channel = new_channel
                channels[current_channel][current_username] = websocket
                
                # 更新连接映射
                connection_map[websocket] = (current_username, current_channel, is_admin)
                
                # 广播用户加入新频道消息
                await broadcast(current_channel, {
                    "type": "system",
                    "message": f"{current_username} 加入了频道"
                })
                
                # 通知用户切换成功
                await websocket.send(json.dumps({
                    "type": "system",
                    "channel": current_channel,
                    "message": f"已切换到频道 '{current_channel}'"
                }))
            
            # 处理查看用户列表命令
            elif data.get('action') == 'list_command':
                channel_id = data.get('channel_id')
                
                if channel_id not in ALLOWED_CHANNELS:
                    await websocket.send(json.dumps({
                        "type": "error",
                        "channel": current_channel or "unknown",
                        "message": f"频道 '{channel_id}' 不被允许或不存在"
                    }))
                    continue
                
                # 获取频道用户列表
                if channel_id in channels and channels[channel_id]:
                    users = list(channels[channel_id].keys())
                    user_list = "    ".join(users)  # 4个空格分隔
                    await websocket.send(json.dumps({
                        "type": "user_list",
                        "channel": channel_id,
                        "message": f"频道 {channel_id} 在线用户 ({len(users)}):",
                        "users": user_list
                    }))
                else:
                    await websocket.send(json.dumps({
                        "type": "system",
                        "channel": current_channel or "unknown",
                        "message": f"频道 {channel_id} 中没有在线用户"
                    }))
            
            # 处理管理员命令
            elif data.get('action') == 'admin_command':
                if not is_admin:
                    await websocket.send(json.dumps({
                        "type": "error",
                        "channel": current_channel or "unknown",
                        "message": "你没有权限执行此命令"
                    }))
                    continue
                
                await handle_admin_command(websocket, data.get('command', ''), current_username)
            
            # 处理普通消息
            elif data.get('action') == 'message':
                if not current_username or not current_channel or not login_completed:
                    # 确保登录完成后才能发送消息
                    continue
                    
                message_text = data.get('message', '').strip()
                if message_text:
                    await broadcast(current_channel, {
                        "type": "message",
                        "username": current_username,
                        "message": message_text
                    })
            
            # 处理离开请求
            elif data.get('action') == 'leave':
                if current_username and current_channel and current_username in channels[current_channel]:
                    del channels[current_channel][current_username]
                    await broadcast(current_channel, {
                        "type": "system",
                        "message": f"{current_username} 离开了频道"
                    })
                break
                
        # 断开连接时清理
        if current_username and current_channel and current_username in channels[current_channel]:
            del channels[current_channel][current_username]
            await broadcast(current_channel, {
                "type": "system",
                "message": f"{current_username} 离开了频道"
            })
            
        # 从连接映射移除
        if websocket in connection_map:
            del connection_map[websocket]
                
    except websockets.exceptions.ConnectionClosed:
        # 客户端意外断开连接
        if current_username and current_channel and current_username in channels[current_channel]:
            del channels[current_channel][current_username]
            await broadcast(current_channel, {
                "type": "system",
                "message": f"{current_username} 已断开连接"
            })
        
        # 从连接映射移除
        if websocket in connection_map:
            del connection_map[websocket]
    except Exception as e:
        print(f"处理客户端错误: {e}")

async def main():
    async with websockets.serve(handle_client, "0.0.0.0", 8765):
        print(f"聊天服务器已启动，监听端口 8765")
        print(f"允许的频道: {', '.join(ALLOWED_CHANNELS)}")
        await asyncio.Future()  # 运行 forever

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n服务器已关闭")
    