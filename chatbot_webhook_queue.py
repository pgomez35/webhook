"""
Cola in-process para procesar webhooks chatbot fuera del request HTTP.

Objetivo: ACK 200 rápido a Meta sin esperar OpenAI/FAQ/envíos.
Talentum Manager sigue procesándose en el request (sin cambios).

Control por env:
  CHATBOT_WEBHOOK_ASYNC=1|0     (default 1)
  CHATBOT_WEBHOOK_WORKERS=2
  CHATBOT_WEBHOOK_QUEUE_MAX=200
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Dict, Optional

logger = logging.getLogger("uvicorn.error")


def _env_int(name: str, default: int) -> int:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def webhook_async_habilitado() -> bool:
    raw = (os.getenv("CHATBOT_WEBHOOK_ASYNC") or "1").strip().lower()
    return raw not in {"0", "false", "no", "off"}


class ChatbotWebhookQueue:
    def __init__(
        self,
        *,
        workers: Optional[int] = None,
        maxsize: Optional[int] = None,
    ) -> None:
        self.workers_n = max(1, workers if workers is not None else _env_int("CHATBOT_WEBHOOK_WORKERS", 2))
        self.maxsize = max(
            1, maxsize if maxsize is not None else _env_int("CHATBOT_WEBHOOK_QUEUE_MAX", 200)
        )
        self._queue: Optional[asyncio.Queue] = None
        self._tasks: list[asyncio.Task] = []
        self._started = False
        self._enqueued = 0
        self._processed = 0
        self._failed = 0
        self._rejected = 0

    @property
    def started(self) -> bool:
        return self._started

    def stats(self) -> Dict[str, Any]:
        qsize = self._queue.qsize() if self._queue is not None else 0
        return {
            "started": self._started,
            "workers": self.workers_n,
            "maxsize": self.maxsize,
            "qsize": qsize,
            "enqueued": self._enqueued,
            "processed": self._processed,
            "failed": self._failed,
            "rejected": self._rejected,
        }

    async def start(self) -> None:
        if self._started:
            return
        self._queue = asyncio.Queue(maxsize=self.maxsize)
        self._tasks = [
            asyncio.create_task(self._worker(i), name=f"chatbot-webhook-worker-{i}")
            for i in range(self.workers_n)
        ]
        self._started = True
        logger.info(
            "[CHATBOT_WEBHOOK_QUEUE] started workers=%s maxsize=%s",
            self.workers_n,
            self.maxsize,
        )
        print(
            f"[CHATBOT_WEBHOOK_QUEUE] started workers={self.workers_n} "
            f"maxsize={self.maxsize}"
        )

    async def stop(self, *, drain_timeout: float = 5.0) -> None:
        if not self._started:
            return
        for t in self._tasks:
            t.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks = []
        self._started = False
        logger.info("[CHATBOT_WEBHOOK_QUEUE] stopped stats=%s", self.stats())

    def try_enqueue(self, job: Dict[str, Any]) -> bool:
        """
        Encola sin await. True si entró; False si cola llena o no iniciada.
        """
        if not self._started or self._queue is None:
            self._rejected += 1
            return False
        try:
            self._queue.put_nowait(job)
            self._enqueued += 1
            return True
        except asyncio.QueueFull:
            self._rejected += 1
            logger.warning(
                "[CHATBOT_WEBHOOK_QUEUE] FULL rejected qsize=%s maxsize=%s",
                self._queue.qsize(),
                self.maxsize,
            )
            print(
                f"[CHATBOT_WEBHOOK_QUEUE] FULL rejected "
                f"qsize={self._queue.qsize()} maxsize={self.maxsize}"
            )
            return False

    async def _worker(self, idx: int) -> None:
        assert self._queue is not None
        while True:
            job = await self._queue.get()
            try:
                await self._procesar_job(job)
                self._processed += 1
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                self._failed += 1
                logger.exception(
                    "[CHATBOT_WEBHOOK_QUEUE] worker=%s job failed: %s", idx, exc
                )
                print(f"❌ [CHATBOT_WEBHOOK_QUEUE] worker={idx} error: {exc}")
            finally:
                self._queue.task_done()

    async def _procesar_job(self, job: Dict[str, Any]) -> None:
        from tenant import (
            current_business_name,
            current_phone_id,
            current_tenant,
            current_token,
        )
        from main_webhook import _procesar_mensaje_unico

        token = job.get("token")
        phone_number_id = job.get("phone_number_id")
        tenant_name = job.get("tenant_name") or "chatbot"
        business_name = job.get("business_name")

        tok_t = current_token.set(token)
        ph_t = current_phone_id.set(phone_number_id)
        ten_t = current_tenant.set(tenant_name)
        biz_t = None
        if business_name is not None:
            biz_t = current_business_name.set(business_name)

        request_id = job.get("request_id")
        print(
            f"[CHATBOT_WEBHOOK_QUEUE] process "
            f"request_id={request_id} "
            f"incoming_wamid={job.get('mensaje_id')} "
            f"agencia_id={job.get('chatbot_agencia_id')}"
        )
        try:
            await _procesar_mensaje_unico(
                job["mensaje"],
                tenant_name,
                phone_number_id,
                token,
                job.get("chatbot_agencia_id"),
                job.get("whatsapp_account_id"),
                "chatbot",
            )
        finally:
            current_token.reset(tok_t)
            current_phone_id.reset(ph_t)
            current_tenant.reset(ten_t)
            if biz_t is not None:
                current_business_name.reset(biz_t)


_queue: Optional[ChatbotWebhookQueue] = None


def get_chatbot_webhook_queue() -> ChatbotWebhookQueue:
    global _queue
    if _queue is None:
        _queue = ChatbotWebhookQueue()
    return _queue


async def start_chatbot_webhook_queue() -> None:
    q = get_chatbot_webhook_queue()
    await q.start()


async def stop_chatbot_webhook_queue() -> None:
    q = get_chatbot_webhook_queue()
    await q.stop()


def encolar_mensaje_chatbot(job: Dict[str, Any]) -> bool:
    """API pública para el webhook. False → caller puede hacer fallback sync."""
    if not webhook_async_habilitado():
        return False
    return get_chatbot_webhook_queue().try_enqueue(job)
