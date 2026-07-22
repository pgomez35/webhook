# rev=e89b7524 lines=4462-4552 count=91
@app.api_route("/meta/exchange_code", methods=["GET", "POST", "OPTIONS"])
async def exchange_code(request: Request):
    """Intercambia el 'code' OAuth de Meta por un access_token temporal.
    Si el WABA ID ya está en base de datos, completa la vinculación automáticamente.
    """

    # ✅ Manejo de preflight (CORS)
    if request.method == "OPTIONS":
        return JSONResponse(
            status_code=200,
            headers={
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
                "Access-Control-Allow-Headers": "Content-Type",
            },
        )

    try:
        # ✅ Obtener parámetros según método
        if request.method == "GET":
            code = request.query_params.get("code")
            redirect_uri = request.query_params.get("redirect_uri", META_REDIRECT_URL)
        else:
            payload = await request.json()
            code = payload.get("code")
            redirect_uri = payload.get("redirect_uri", META_REDIRECT_URL)

        if not code:
            return JSONResponse(
                status_code=400,
                content={"error": "missing_code", "message": "El parámetro 'code' es requerido"},
                headers={"Access-Control-Allow-Origin": "*"}
            )

        logging.info(f"📥 Código OAuth recibido: {code[:6]}...{code[-6:]}")
        logging.info("🔄 Intercambiando code con Meta...")

        # ✅ Solicitud a Meta
        token_url = f"https://graph.facebook.com/{GRAPH_API_VERSION}/oauth/access_token"
        params = {
            "code": code,
            "client_id": META_APP_ID,
            "client_secret": META_APP_SECRET
        }
        r = requests.get(token_url, params=params, timeout=30)
        data = r.json()

        logging.info(f"📤 Respuesta Meta: {json.dumps(data, indent=2)}")

        # ✅ Validar respuesta
        access_token = data.get("access_token")
        if not access_token:
            return JSONResponse(
                status_code=400,
                content={"error": "no_access_token", "message": "Meta no devolvió access_token"},
                headers={"Access-Control-Allow-Origin": "*"}
            )

        # 🆔 Sesión temporal
        session_id = "abc123"

        # ✅ Guardar o actualizar token en DB
        resultado_token = guardar_o_actualizar_token_db(session_id, access_token)

        # ✅ Si existe WABA y TOKEN, completar vínculo y actualizar phone info
        if resultado_token["status"] == "completado":
            actualizado = actualizar_info_phone(resultado_token)
            if actualizado:
                logging.info(f"📞 Phone info actualizada para WABA {resultado_token['waba_id']}")

        # ✅ Respuesta final
        return JSONResponse(
            status_code=200,
            content={
                "status": resultado_token["status"],
                "waba_id": resultado_token.get("waba_id"),
                "id": resultado_token.get("id"),
                "message": "Token procesado correctamente."
            },
            headers={"Access-Control-Allow-Origin": "*"}
        )

    except Exception as e:
        logging.exception("❌ Error inesperado en /meta/exchange_code")
        return JSONResponse(
            status_code=500,
            content={"error": "internal_error", "message": str(e)},
            headers={"Access-Control-Allow-Origin": "*"}
        )


