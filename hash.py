import hashlib

def calculate_string_sha256(input_string):
    """计算字符串的SHA-256哈希值"""
    # 创建SHA-256哈希对象
    sha256_hash = hashlib.sha256()
    
    # 更新哈希对象，需要将字符串编码为字节
    sha256_hash.update(input_string.encode('utf-8'))
    
    # 获取十六进制格式的哈希值
    return sha256_hash.hexdigest()

def calculate_file_sha256(file_path, chunk_size=65536):
    """计算文件的SHA-256哈希值"""
    # 创建SHA-256哈希对象
    sha256_hash = hashlib.sha256()
    
    try:
        # 以二进制模式打开文件
        with open(file_path, 'rb') as file:
            # 分块读取文件以处理大文件
            while chunk := file.read(chunk_size):
                sha256_hash.update(chunk)
        
        # 返回十六进制格式的哈希值
        return sha256_hash.hexdigest()
    except FileNotFoundError:
        return f"错误: 文件 '{file_path}' 未找到"
    except Exception as e:
        return f"计算哈希时出错: {str(e)}"

if __name__ == "__main__":
    # 示例：计算字符串的SHA-256哈希
    test_string = ""
    string_hash = calculate_string_sha256(test_string)
    print(f"字符串 '{test_string}' 的SHA-256哈希:")
    print(string_hash)
    
    # 示例：计算文件的SHA-256哈希（将文件名替换为实际文件）
    # file_hash = calculate_file_sha256("example.txt")
    # print(f"\n文件的SHA-256哈希:")
    # print(file_hash)
