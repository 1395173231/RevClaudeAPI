import asyncio

from fastapi import APIRouter, Depends, Query, Request, BackgroundTasks
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi import Header, HTTPException
from api_key_manage import APIKeyManager, get_api_key_manager



from schemas import ClaudeChatRequest
from loguru import logger

from models import ClaudeModels

# This in only for claude router, I do not use the


# async def validate_api_key(
#     api_key: str = Header(None), manager: APIKeyManager = Depends(get_api_key_manager)
# ):
async def validate_api_key(request: Request, manager: APIKeyManager = Depends(get_api_key_manager)
):
    # return
    # Authorization
    logger.info(f"headers: {request.headers}")
    api_key = request.headers.get("Authorization")
    logger.info(f"checking api key: {api_key}")
    if api_key is None or not manager.is_api_key_valid(api_key):
        raise HTTPException(status_code=403, detail="Invalid or missing API key")
    manager.increment_usage(api_key)


router = APIRouter(dependencies=[Depends(validate_api_key)])


def obtain_claude_client():
    from main import client_round_robin

    return client_round_robin


async def patched_generate_data(original_generator, conversation_id):
    # 首先发送 conversation_id
    yield f"<{conversation_id}>"

    # 然后，对原始生成器进行迭代，产生剩余的数据
    async for data in original_generator:
        yield data

#
# @router.get("/list_conversations")
# async def list_conversations(claude_client=Depends(obtain_claude_client)):
#     return claude_client.list_all_conversations()
#     # return {"message": "Hello World"}


@router.get("/list_models")
async def list_models():
    return [model.value for model in ClaudeModels]


@router.post("/chat")
async def chat(
        request: Request,
    claude_chat_request: ClaudeChatRequest, claude_clients_round_robin=Depends(obtain_claude_client)
, manager: APIKeyManager = Depends(get_api_key_manager)
):
    logger.info(f"headers: {request.headers}")
    api_key = request.headers.get("Authorization")

    model = claude_chat_request.model
    if model not in [model.value for model in ClaudeModels]:
        return JSONResponse(
            status_code=400,
            content={"error": f"Model not found."},
        )
    conversation_id = claude_chat_request.conversation_id
    if ClaudeModels.model_is_plus(model):
        if not manager.is_plus_user(api_key):
            return JSONResponse(
                status_code=403,
                content={"error": f"API key is not a plus user, please upgrade your plant to access this model."},
            )
        claude_client = claude_clients_round_robin.get_next_plus_client()
    else:
        claude_client = claude_clients_round_robin.get_next_basic_client()
    # claude_client
    # conversation_id = "test"
    max_retry = 3
    current_retry = 0
    # conversation_id = "test"
    max_retry = 3
    current_retry = 0
    while current_retry < max_retry:
        try:
            if not conversation_id:
                try:
                    conversation = claude_client.create_new_chat(model=model)
                    logger.info(f"Created new conversation: {conversation}")
                    conversation_id = conversation["uuid"]
                    logger.info(f"Created new conversation with id: {conversation_id}")
                    break  # 成功创建对话后跳出循环
                except Exception as e:
                    current_retry += 1
                    logger.error(f"Failed to create conversation. Retry {current_retry}/{max_retry}. Error: {e}")
                    if current_retry == max_retry:
                        logger.error(f"Failed to create conversation after {max_retry} retries.")
                        return ("error: ", e)
                    else:
                        logger.info("Retrying in 1 second...")
                        await asyncio.sleep(1)
            else:
                logger.info(f"Using existing conversation with id: {conversation_id}")
                break
        except Exception as e:
            logger.error(f"Meet an error: {e}")
            return ("error: ", e)



    message = claude_chat_request.message
    is_stream = claude_chat_request.stream

    if is_stream:
        streaming_res = claude_client.stream_message(message, conversation_id, model)
        streaming_res = patched_generate_data(streaming_res, conversation_id)
        return StreamingResponse(
            streaming_res,
            media_type="text/event-stream",
            headers={
                "conversation_id": conversation_id
            },  # 这里通过header返回conversation_id
        )
    else:
        res = claude_client.send_message(message, conversation_id, model)
        return res
