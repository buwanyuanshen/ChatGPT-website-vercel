# -*- coding: utf-8 -*-
from datetime import datetime, timedelta
from flask import Flask, request, jsonify, render_template, Response
import requests
import json
import os
import random
import base64
import re

app = Flask(__name__)


@app.route("/", methods=["GET"])
def index():
    """
    渲染并返回前端的主聊天页面。
    """
    return render_template("chat.html")
    
@app.route("/models", methods=["GET"])
def get_models():
    """
    从后端API获取可用模型列表。
    支持前端传入自定义的 apiKey 和 api_url，如果未提供，则使用服务器环境变量中的默认配置。
    """
    # 从前端的查询参数中获取 apiKey 和 api_url
    apiKey = request.args.get("apiKey", None)
    api_url = request.args.get("api_url", None)

    # 如果前端未提供 api_url，则使用服务器配置的默认 URL
    if not api_url:
        api_url = os.environ.get("API_URL1", None)

    # 如果前端未提供 apiKey，则从服务器配置的密钥池中随机选择一个
    if not apiKey:
        api_keys_str = os.environ.get("API_KEYS1", None)
        if not api_keys_str:
             return jsonify({"error": {"message": "服务器没有配置默认的 API 密钥。", "type": "config_error"}}), 500
        api_keys = api_keys_str.strip().split(",")
        apiKey = random.choice(api_keys)

    # 确保最终有可用的 apiKey 和 api_url
    if not apiKey or not api_url:
        return jsonify({"error": {"message": "缺少 API 密钥或 URL。", "type": "config_error"}}), 400

    headers = {
        "Authorization": f"Bearer {apiKey}",
        "Content-Type": "application/json"
    }
    
    # 构建请求模型列表的完整 URL
    models_url = f"{api_url.rstrip('/')}/v1/models"

    try:
        # 发送 GET 请求获取模型列表
        resp = requests.get(models_url, headers=headers, timeout=15)
        resp.raise_for_status()  # 如果请求失败 (状态码 4xx 或 5xx)，则抛出异常
        models_data = resp.json()
        
        # 如果返回的数据中包含模型列表，则按模型ID字母顺序排序
        if 'data' in models_data and isinstance(models_data['data'], list):
            models_data['data'] = sorted(models_data['data'], key=lambda x: x.get('id', ''))
            
        return jsonify(models_data)
        
    except requests.exceptions.RequestException as e:
        # 处理网络请求相关的异常
        return jsonify({"error": {"message": f"从API获取模型失败: {str(e)}", "type": "api_error"}}), 500
    except Exception as e:
        # 处理其他未知异常
        return jsonify({"error": {"message": f"发生未知错误: {str(e)}", "type": "internal_error"}}), 500

@app.route("/default_balance", methods=["GET"])
def get_balance():
    """
    查询 API 密钥的余额信息。
    优先使用用户在前端提供的 apiKey 和 api_url，如果未提供，则回退到服务器的默认配置。
    """
    # 从前端请求中获取用户自定义的 apiKey 和 api_url
    user_api_key = request.args.get("apiKey", None)
    user_api_url = request.args.get("api_url", None)

    # --- 智能回退逻辑 ---
    # 如果用户提供了 apiKey，则使用用户的；否则，从服务器默认密钥池中选择一个。
    if user_api_key:
        final_api_key = user_api_key
    else:
        api_keys_str = os.environ.get("API_KEYS1", None)
        if not api_keys_str:
             return jsonify({"error": {"message": "未设置默认的 API 密钥", "type": "config_error"}}), 500
        api_keys = api_keys_str.strip().split(",")
        final_api_key = random.choice(api_keys)

    # 如果用户提供了 api_url，则使用用户的；否则，使用服务器的默认 URL。
    if user_api_url:
        final_api_url = user_api_url
    else:
        final_api_url = os.environ.get("API_URL1", None)
    # --- 智能回退逻辑结束 ---

    # 确保最终有可用的 apiKey 和 api_url
    if not final_api_key or not final_api_url:
        return jsonify({"error": {"message": "未配置 API 密钥或 URL", "type": "config_error"}})

    headers = {
        "Authorization": f"Bearer {final_api_key}",
        "Content-Type": "application/json"
    }

    try:
        # 构建查询订阅信息的 URL 并发送请求
        subscription_url = f"{final_api_url.rstrip('/')}/v1/dashboard/billing/subscription"
        subscription_resp = requests.get(subscription_url, headers=headers, timeout=10)
        subscription_resp.raise_for_status()
        subscription_data = subscription_resp.json()
        total = subscription_data.get('hard_limit_usd', 0)

        # 构建查询使用量的 URL 并发送请求 (查询过去99天)
        start_date = datetime.now() - timedelta(days=99)
        end_date = datetime.now()
        usage_url = f"{final_api_url.rstrip('/')}/v1/dashboard/billing/usage?start_date={start_date.strftime('%Y-%m-%d')}&end_date={end_date.strftime('%Y-%m-%d')}"
        usage_resp = requests.get(usage_url, headers=headers, timeout=10)
        usage_resp.raise_for_status()
        usage_data = usage_resp.json()
        total_usage = usage_data.get('total_usage', 0) / 100
        remaining = total - total_usage

        # 返回格式化的余额信息
        return jsonify({
            "total_balance": total,
            "used_balance": total_usage,
            "remaining_balance": remaining
        })
    except requests.exceptions.RequestException as e:
        # 处理 API 请求相关的错误 (如密钥错误、网络问题)
        return jsonify({"error": {"message": f"API 错误：{str(e)}", "type": "api_error"}})
    except Exception as e:
        # 处理服务器内部的其他错误
        return jsonify({"error": {"message": f"服务器错误：{str(e)}", "type": "server_error"}})


@app.route("/chat", methods=["POST"])
def chat():
    """
    处理核心的聊天、绘图、文本审核等请求。
    这是一个复杂的端点，它会根据用户选择的模型和提供的凭证（API Key或密码）来决定使用哪个后端API和密钥。
    """
    # 从前端表单中获取所有必要的参数
    messages = request.form.get("prompts", None)
    apiKey = request.form.get("apiKey", None)
    model = request.form.get("model", "gpt-5")
    temperature = request.form.get("temperature", 0.5)
    max_tokens = request.form.get("max_tokens", 4000)
    password = request.form.get("password", None)
    api_url = request.form.get("api_url", None)
    image_base64 = request.form.get("image_base64", None)

    # 如果用户没有提供 api_url，则使用服务器默认的 URL
    if api_url is None:
        api_url = os.environ.get("API_URL", None)

    # 从环境变量中加载预设的访问密码
    access_passwords = [
        os.environ.get("ACCESS_PASSWORD_1", None),
        os.environ.get("ACCESS_PASSWORD_2", None),
        os.environ.get("ACCESS_PASSWORD_3", None),
        os.environ.get("ACCESS_PASSWORD_4", None),
        os.environ.get("ACCESS_PASSWORD_5", None),
    ]
    
    # 定义需要密码验证的高级模型关键字列表
    premium_models_keywords = [
        "gpt-4", "gpt-5", "dall", "claude", "SparkDesk", "gemini", "grok",
        "o1", "o3", "o4", "chatgpt", "embedding", "moderation", "glm", "yi",
        "commmand", "stable", "deep", "midjourney", "douubao", "qwen", "co",
        "suno", "abab", "chat"
    ]
    
    # 检查当前模型是否为需要密码的高级模型
    is_premium_model = any(keyword in model for keyword in premium_models_keywords)

    # --- 密钥和密码验证与选择逻辑 ---
    if apiKey is None:
        if is_premium_model:
            # 如果是高级模型且没有提供 apiKey，则必须提供密码
            if not password:
                return jsonify({"error": {"message": "请联系群主获取授权码或者输入自己的apikey！！！",
                                          "type": "empty_password_error", "code": ""}})
            if password not in access_passwords:
                return jsonify({"error": {"message": "请检查并输入正确的授权码或者输入自己的apikey！！！",
                                          "type": "invalid_password_error", "code": ""}})
            
            # 根据匹配的密码，选择对应的 API 密钥池和 URL
            if password == os.environ.get("ACCESS_PASSWORD_1", None):
                api_keys = os.environ.get("API_KEYS1", "").strip().split(",")
                apiKey = random.choice(api_keys) if api_keys else None
                api_url = os.environ.get("API_URL1", None)
            elif password == os.environ.get("ACCESS_PASSWORD_2", None):
                api_keys = os.environ.get("API_KEYS2", "").strip().split(",")
                apiKey = random.choice(api_keys) if api_keys else None
                api_url = os.environ.get("API_URL2", None)
            elif password == os.environ.get("ACCESS_PASSWORD_3", None):
                api_keys = os.environ.get("API_KEYS3", "").strip().split(",")
                apiKey = random.choice(api_keys) if api_keys else None
                api_url = os.environ.get("API_URL3", None)
            elif password == os.environ.get("ACCESS_PASSWORD_4", None):
                api_keys = os.environ.get("API_KEYS4", "").strip().split(",")
                apiKey = random.choice(api_keys) if api_keys else None
                api_url = os.environ.get("API_URL4", None)
            elif password == os.environ.get("ACCESS_PASSWORD_5", None):
                api_keys = os.environ.get("API_KEYS5", "").strip().split(",")
                apiKey = random.choice(api_keys) if api_keys else None
                api_url = os.environ.get("API_URL5", None)
        else:
            # 如果是普通模型且没有提供 apiKey，则使用默认的密钥池和 URL
            api_keys = os.environ.get("API_KEYS", "").strip().split(",")
            apiKey = random.choice(api_keys) if api_keys else None
            api_url = os.environ.get("API_URL", None)

    # --- 根据模型名称构建请求体 (data) 和 API URL ---
    data = None # 初始化 data 变量
    
    # 图像生成模型 (DALL-E, CogView)
    if "dall-e" in model or "cogview" in model:
        api_url += "/v1/images/generations"
        data = {"prompt": messages, "n": 1}
        if model == "dall-e-2": data.update({"model": "dall-e-2", "size": "256x256"})
        elif model == "dall-e-2-m": data.update({"model": "dall-e-2", "size": "512x512"})
        elif model == "dall-e-2-l": data.update({"model": "dall-e-2", "size": "1024x1024"})
        elif model == "dall-e-3": data.update({"model": "dall-e-3", "size": "1024x1024", "quality": "standard", "style": "natural"})
        elif model == "dall-e-3-w": data.update({"model": "dall-e-3", "size": "1792x1024", "quality": "standard", "style": "natural"})
        elif model == "dall-e-3-l": data.update({"model": "dall-e-3", "size": "1024x1792", "quality": "standard", "style": "natural"})
        elif model == "dall-e-3-hd": data.update({"model": "dall-e-3", "size": "1024x1024", "quality": "hd", "style": "natural"})
        elif model == "dall-e-3-w-hd": data.update({"model": "dall-e-3", "size": "1792x1024", "quality": "hd", "style": "natural"})
        elif model == "dall-e-3-l-hd": data.update({"model": "dall-e-3", "size": "1024x1792", "quality": "hd", "style": "natural"})
        elif model == "dall-e-3-v": data.update({"model": "dall-e-3", "size": "1024x1024", "quality": "standard", "style": "vivid"})
        elif model == "dall-e-3-w-v": data.update({"model": "dall-e-3", "size": "1792x1024", "quality": "standard", "style": "vivid"})
        elif model == "dall-e-3-l-v": data.update({"model": "dall-e-3", "size": "1024x1792", "quality": "standard", "style": "vivid"})
        elif model == "dall-e-3-p": data.update({"model": "dall-e-3", "size": "1024x1024", "quality": "hd", "style": "vivid"})
        elif model == "dall-e-3-w-p": data.update({"model": "dall-e-3", "size": "1792x1024", "quality": "hd", "style": "vivid"})
        elif model == "dall-e-3-l-p": data.update({"model": "dall-e-3", "size": "1024x1792", "quality": "hd", "style": "vivid"})
        elif model == "cogview-3": data.update({"model": "cogview-3", "size": "1024x1024"})
        elif model == "cogview-3-plus": data.update({"model": "cogview-3-plus", "size": "1024x1024"})
    
    # 文本审核模型
    elif "moderation" in model:
        api_url += "/v1/moderations"
        data = {"input": messages, "model": model}
    
    # 文本嵌入模型
    elif "embedding" in model:
        api_url += "/v1/embeddings"
        data = {"input": messages, "model": model}
    
    # 文本转语音模型 (TTS)
    elif "tts" in model:
        api_url += "/v1/audio/speech"
        data = {"input": messages.replace("user", "").replace("content", "").replace("role", "").replace("assistant", ""), "model": model, "voice": "alloy"}

    # 旧版的文本补全模型
    elif "gpt-3.5-turbo-instruct" in model or "babbage-002" in model or "davinci-002" in model:
        api_url += "/v1/completions"
        data = {"prompt": messages, "model": model, "max_tokens": int(max_tokens), "temperature": float(temperature), "top_p": 1, "n": 1, "stream": True}
    
    # 视觉或高级对话模型
    elif any(keyword in model for keyword in ["gpt-4", "gpt-5", "vision", "glm-4v", "claude-sonnet", "claude-opus", "claude-3", "gemini-1.5", "o1", "o3", "o4"]):
        api_url += "/v1/chat/completions"
        # 如果有图像数据，则构建包含图像的请求体
        if image_base64:
            data = {
                "messages": [{"role": "user", "content": [{"type": "text", "text": messages}, {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"}}]}],
                "model": model, "max_tokens": int(max_tokens), "stream": True
            }
        # 针对特定模型的参数微调
        elif "claude-3" in model or "claude-sonnet" in model or "claude-opus" in model:
            data = {"messages": json.loads(messages), "model": model, "max_tokens": int(max_tokens), "n": 1, "stream": True}
        elif "o1" in model and "all" not in model:
            data = {"messages": json.loads(messages), "model": model, "max_tokens": int(max_tokens), "temperature": 1, "top_p": 1, "n": 1, "stream": True}
        elif "o3" in model and "all" not in model:
            data = {"messages": json.loads(messages), "model": model, "max_tokens": int(max_tokens), "temperature": 1, "top_p": 1, "n": 1, "stream": True}
        elif "o4" in model and "all" not in model:
            data = {"messages": json.loads(messages), "model": model, "max_tokens": int(max_tokens), "temperature": 1, "top_p": 1, "n": 1, "stream": True}
        # FIX: 此处修复了原始代码中的缩进错误
        elif "gpt-5" in model and "all" not in model:
            data = {"messages": json.loads(messages), "model": model, "max_tokens": int(max_tokens), "temperature": 1, "top_p": 1, "n": 1, "stream": True}
        # 其他高级模型的默认配置
        else:
            data = {"messages": json.loads(messages), "model": model, "max_tokens": int(max_tokens), "temperature": float(temperature), "top_p": 1, "n": 1, "stream": True}
    
    # 其他特定模型的配置
    elif "grok-3-mini" in model:
        api_url += "/v1/chat/completions"
        data = {"messages": json.loads(messages), "model": model, "max_tokens": int(max_tokens), "temperature": float(temperature), "top_p": 1, "n": 1, "stream": True}
    elif "grok-2-image" in model:
        api_url += "/v1/chat/completions"
        data = {"messages": json.loads(messages), "model": model, "n": 1}
    elif "deepseek-r" in model:
        api_url += "/v1/chat/completions"
        data = {"messages": json.loads(messages), "model": model, "max_tokens": int(max_tokens), "n": 1, "stream": True}
        
    # 默认的聊天补全模型
    else:
        api_url += "/v1/chat/completions"
        data = {"messages": json.loads(messages), "model": model, "max_tokens": int(max_tokens), "temperature": float(temperature), "top_p": 1, "n": 1, "stream": True}

    # 确保请求体已成功构建
    if data is None:
        return jsonify({"error": {"message": "无法处理该请求，请求体构建失败。", "type": "data_error", "code": ""}})

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {apiKey}",
    }

    try:
        # 发送 POST 请求到目标 API
        resp = requests.post(
            url=api_url,
            headers=headers,
            json=data,
            stream=True,  # 开启流式传输
            timeout=(60, 60) # 设置连接和读取超时
        )
    except requests.exceptions.Timeout:
        return jsonify({"error": {"message": "请求超时", "type": "timeout_error", "code": ""}})
    except Exception as e:
        return jsonify({"error": {"message": str(e), "type": "unexpected_error", "code": ""}})

    # --- 根据模型类型处理不同的响应 ---

    # DALL-E 模型的响应处理：返回图片 URL
    if "dall-e" in model:
        response_data = json.loads(resp.content.decode('utf-8'))
        image_url = response_data["data"][0]["url"]
        return jsonify(image_url)

    # 文本审核模型的响应处理：格式化并返回审核结果
    if "moderation" in model:
        response_data = json.loads(resp.content.decode('utf-8'))
        results = response_data.get("results", [])
        formatted_results = []
        # 定义一个类别映射以简化代码
        category_map = {
            "hate": "仇恨", "hate/threatening": "威胁性仇恨", "harassment": "骚扰",
            "harassment/threatening": "威胁性骚扰", "self-harm": "自残",
            "self-harm/intent": "自残意图", "self-harm/instructions": "自残说明",
            "sexual": "性内容", "sexual/minors": "未成年人性内容", "violence": "暴力",
            "violence/graphic": "图文暴力", "illicit": "非法", "illicit/violent": "非法/暴力"
        }
        for res in results:
            categories_bool = {name: res["categories"][key] for key, name in category_map.items() if key in res["categories"]}
            category_scores = {f"{name}分数": res["category_scores"][key] for key, name in category_map.items() if key in res["category_scores"]}
            formatted_results.append({
                "有害标记": res.get("flagged"),
                "违规类别": categories_bool,
                "违规类别分数(越大置信度越高)": category_scores
            })
        return json.dumps(formatted_results, ensure_ascii=False, indent=2)
        
    # 文本嵌入模型的响应处理：返回嵌入向量
    if "embedding" in model:
        response_data = json.loads(resp.content.decode('utf-8'))
        embedding = response_data["data"][0]["embedding"]
        return jsonify(embedding)

    # TTS 模型的响应处理：返回 Base64 编码的音频数据
    if "tts" in model:
        audio_data = base64.b64encode(resp.content).decode('utf-8')
        return jsonify(audio_data)

    # 对话模型的流式响应处理
    def generate():
        errorStr = ""
        respStr = ""
        for chunk in resp.iter_lines():
            if chunk:
                # SSE (Server-Sent Events) 格式的数据以 "data: " 开头
                streamStr = chunk.decode("utf-8").replace("data: ", "")
                if not streamStr.strip() or streamStr.strip() == "[DONE]":
                    continue # 跳过空行和结束标记

                try:
                    streamDict = json.loads(streamStr)
                except json.JSONDecodeError:
                    errorStr += streamStr.strip() # 如果解析失败，可能是错误信息
                    continue
                
                # 检查响应中是否包含 'choices' 字段
                if "choices" in streamDict and streamDict["choices"]:
                    choice = streamDict["choices"][0]
                    content = ""
                    # 兼容不同 API 返回的响应结构
                    if "text" in choice:
                        content = choice["text"]
                    elif "delta" in choice and "content" in choice["delta"]:
                        content = choice["delta"]["content"]
                        # 特殊处理带思考过程的响应
                        if "reasoning_content" in choice["delta"] and choice["delta"]["reasoning_content"]:
                            content = f"思考过程：\n{choice['delta']['reasoning_content']}\n最终回答：\n{content or ''}"
                    elif "message" in choice and "content" in choice["message"]:
                        content = choice["message"]["content"]
                        if "reasoning_content" in choice["message"] and choice["message"]["reasoning_content"]:
                            content = f"思考过程：\n{choice['message']['reasoning_content']}\n最终回答：\n{content or ''}"
                    
                    if content:
                        respStr += content
                        yield content
                
                # 检查响应中是否包含错误信息
                elif "error" in streamDict:
                    error_msg = streamDict['error'].get('message', '未知错误')
                    errorStr += f"API 错误: {error_msg}\n"
                else:
                    # 记录未知的响应格式
                    errorStr += f"未知的响应格式: {json.dumps(streamDict)}\n"

        # 如果整个流结束了都没有有效内容，但有错误信息，则返回错误信息
        if not respStr and errorStr:
            with app.app_context():
                yield errorStr

    # 返回一个流式响应对象
    return Response(generate(), content_type='application/octet-stream')


if __name__ == '__main__':
    app.run()
