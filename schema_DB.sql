--
-- PostgreSQL database dump
--

\restrict k80fjJecMb7lNvzbg1UycdtAHpPhvtGdu0nL3VaB1WCnE0bUe3NRP133cHXhmDj

-- Dumped from database version 16.13 (Debian 16.13-1.pgdg12+1)
-- Dumped by pg_dump version 18.4

-- Started on 2026-07-22 08:49:14

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET transaction_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- TOC entry 4491 (class 1262 OID 16389)
-- Name: whatsapp_db_vsfq; Type: DATABASE; Schema: -; Owner: whatsapp_db_vsfq_user
--

CREATE DATABASE whatsapp_db_vsfq WITH TEMPLATE = template0 ENCODING = 'UTF8' LOCALE_PROVIDER = libc LOCALE = 'en_US.UTF8';


ALTER DATABASE whatsapp_db_vsfq OWNER TO whatsapp_db_vsfq_user;

\unrestrict k80fjJecMb7lNvzbg1UycdtAHpPhvtGdu0nL3VaB1WCnE0bUe3NRP133cHXhmDj
\connect whatsapp_db_vsfq
\restrict k80fjJecMb7lNvzbg1UycdtAHpPhvtGdu0nL3VaB1WCnE0bUe3NRP133cHXhmDj

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET transaction_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- TOC entry 4492 (class 0 OID 0)
-- Name: whatsapp_db_vsfq; Type: DATABASE PROPERTIES; Schema: -; Owner: whatsapp_db_vsfq_user
--

ALTER DATABASE whatsapp_db_vsfq SET "TimeZone" TO 'utc';


\unrestrict k80fjJecMb7lNvzbg1UycdtAHpPhvtGdu0nL3VaB1WCnE0bUe3NRP133cHXhmDj
\connect whatsapp_db_vsfq
\restrict k80fjJecMb7lNvzbg1UycdtAHpPhvtGdu0nL3VaB1WCnE0bUe3NRP133cHXhmDj

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET transaction_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- TOC entry 265 (class 1259 OID 19373)
-- Name: administradores; Type: TABLE; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE TABLE test.administradores (
    id integer DEFAULT nextval('public.admin_usuario_id_seq'::regclass) NOT NULL,
    username character varying(50) NOT NULL,
    password_hash text NOT NULL,
    nombre_completo character varying(100),
    email character varying(100),
    telefono character varying(20),
    grupo character varying(50),
    activo boolean DEFAULT true,
    creado_en timestamp without time zone DEFAULT now(),
    actualizado_en timestamp without time zone DEFAULT now(),
    administradores_roles_id integer,
    agente character varying(100)
);


ALTER TABLE test.administradores OWNER TO whatsapp_db_vsfq_user;

--
-- TOC entry 273 (class 1259 OID 19547)
-- Name: administradores_roles; Type: TABLE; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE TABLE test.administradores_roles (
    id integer DEFAULT nextval('public.roles_id_seq'::regclass) NOT NULL,
    nombre character varying(50) NOT NULL,
    descripcion text
);


ALTER TABLE test.administradores_roles OWNER TO whatsapp_db_vsfq_user;

--
-- TOC entry 266 (class 1259 OID 19386)
-- Name: agendamientos; Type: TABLE; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE TABLE test.agendamientos (
    id integer DEFAULT nextval('public.agendamientos_id_seq'::regclass) NOT NULL,
    titulo character varying(200),
    descripcion character varying(200),
    fecha_inicio timestamp without time zone,
    fecha_fin timestamp without time zone,
    responsable_id integer,
    link_meet character varying(100),
    google_event_id character varying(100),
    creado_en timestamp without time zone DEFAULT now(),
    actualizado_en timestamp without time zone DEFAULT now(),
    timezone character varying(50),
    tipo_agendamiento integer,
    estado_id integer,
    medio_reunion_id integer
);


ALTER TABLE test.agendamientos OWNER TO whatsapp_db_vsfq_user;

--
-- TOC entry 345 (class 1259 OID 21163)
-- Name: agendamientos_estados; Type: TABLE; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE TABLE test.agendamientos_estados (
    id integer NOT NULL,
    nombre character varying(100) NOT NULL,
    fecha_creacion timestamp without time zone DEFAULT now()
);


ALTER TABLE test.agendamientos_estados OWNER TO whatsapp_db_vsfq_user;

--
-- TOC entry 344 (class 1259 OID 21162)
-- Name: agendamientos_estados_id_seq; Type: SEQUENCE; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE SEQUENCE test.agendamientos_estados_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE test.agendamientos_estados_id_seq OWNER TO whatsapp_db_vsfq_user;

--
-- TOC entry 4493 (class 0 OID 0)
-- Dependencies: 344
-- Name: agendamientos_estados_id_seq; Type: SEQUENCE OWNED BY; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER SEQUENCE test.agendamientos_estados_id_seq OWNED BY test.agendamientos_estados.id;


--
-- TOC entry 282 (class 1259 OID 19721)
-- Name: agendamientos_link_tokens; Type: TABLE; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE TABLE test.agendamientos_link_tokens (
    token text NOT NULL,
    aspirante_id integer NOT NULL,
    responsable_id integer NOT NULL,
    expiracion timestamp without time zone NOT NULL,
    usado boolean DEFAULT false,
    creado_en timestamp without time zone DEFAULT now() NOT NULL,
    duracion_minutos integer DEFAULT 60,
    tipo_agendamiento character varying(30) DEFAULT 'ENTREVISTA'::character varying,
    usado_en timestamp without time zone,
    agendamiento_id integer
);


ALTER TABLE test.agendamientos_link_tokens OWNER TO whatsapp_db_vsfq_user;

--
-- TOC entry 360 (class 1259 OID 21343)
-- Name: agendamientos_medio; Type: TABLE; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE TABLE test.agendamientos_medio (
    id integer NOT NULL,
    codigo character varying(30) NOT NULL,
    nombre character varying(50) NOT NULL,
    requiere_link boolean DEFAULT false,
    activo boolean DEFAULT true,
    creado_en timestamp without time zone DEFAULT now()
);


ALTER TABLE test.agendamientos_medio OWNER TO whatsapp_db_vsfq_user;

--
-- TOC entry 359 (class 1259 OID 21342)
-- Name: agendamientos_medio_id_seq; Type: SEQUENCE; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE SEQUENCE test.agendamientos_medio_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE test.agendamientos_medio_id_seq OWNER TO whatsapp_db_vsfq_user;

--
-- TOC entry 4494 (class 0 OID 0)
-- Dependencies: 359
-- Name: agendamientos_medio_id_seq; Type: SEQUENCE OWNED BY; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER SEQUENCE test.agendamientos_medio_id_seq OWNED BY test.agendamientos_medio.id;


--
-- TOC entry 267 (class 1259 OID 19397)
-- Name: agendamientos_participantes; Type: TABLE; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE TABLE test.agendamientos_participantes (
    id integer DEFAULT nextval('public.agendamientos_participantes_id_seq'::regclass) NOT NULL,
    agendamiento_id integer NOT NULL,
    estado character varying(20) DEFAULT 'pendiente'::character varying,
    participante_tipo_id integer NOT NULL,
    participante_id integer NOT NULL,
    creado_en timestamp without time zone DEFAULT now()
);


ALTER TABLE test.agendamientos_participantes OWNER TO whatsapp_db_vsfq_user;

--
-- TOC entry 290 (class 1259 OID 20121)
-- Name: agendamientos_tipo; Type: TABLE; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE TABLE test.agendamientos_tipo (
    id integer NOT NULL,
    nombre character varying(100) NOT NULL,
    color character varying(20),
    icono character varying(50),
    activo boolean DEFAULT true,
    creado_en timestamp without time zone DEFAULT now(),
    participante_tipo_id integer,
    medio_reunion_id integer
);


ALTER TABLE test.agendamientos_tipo OWNER TO whatsapp_db_vsfq_user;

--
-- TOC entry 269 (class 1259 OID 19427)
-- Name: aspirantes; Type: TABLE; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE TABLE test.aspirantes (
    id integer DEFAULT nextval('public.creadores_id_seq'::regclass) NOT NULL,
    usuario character varying(100),
    nickname character varying(200),
    nombre_real character varying(200),
    email character varying(200),
    telefono character varying(50),
    whatsapp character varying(50),
    foto_url text,
    estado_id integer,
    verificado boolean DEFAULT false,
    fecha_verificacion timestamp without time zone,
    activo boolean DEFAULT true,
    creado_en timestamp without time zone DEFAULT now(),
    actualizado_en timestamp without time zone DEFAULT now(),
    foto_url_mini text,
    rol_id integer DEFAULT 1,
    fecha_solicitud timestamp without time zone,
    encuesta_terminada boolean DEFAULT false,
    tiene_solicitud boolean DEFAULT true NOT NULL,
    zona_horaria character varying(100)
);


ALTER TABLE test.aspirantes OWNER TO whatsapp_db_vsfq_user;

--
-- TOC entry 4495 (class 0 OID 0)
-- Dependencies: 269
-- Name: COLUMN aspirantes.zona_horaria; Type: COMMENT; Schema: test; Owner: whatsapp_db_vsfq_user
--

COMMENT ON COLUMN test.aspirantes.zona_horaria IS 'Zona horaria IANA del aspirante, por ejemplo America/Bogota, America/Mexico_City o Europe/Madrid';


--
-- TOC entry 268 (class 1259 OID 19405)
-- Name: aspirantes_cargue; Type: TABLE; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE TABLE test.aspirantes_cargue (
    id integer DEFAULT nextval('public.cargue_creadores_id_seq'::regclass) NOT NULL,
    usuario character varying(100),
    nickname character varying(200),
    email character varying(200),
    telefono character varying(50),
    disponibilidad character varying(100),
    perfil character varying(100),
    motivo_no_apto text,
    contacto character varying(100),
    respuesta_creador text,
    entrevista character varying(200),
    tipo_solicitud character varying(100),
    razon_no_contacto text,
    seguidores integer DEFAULT 0,
    cantidad_videos integer DEFAULT 0,
    likes_totales bigint DEFAULT 0,
    duracion_emisiones integer DEFAULT 0,
    dias_emisiones integer DEFAULT 0,
    nombre_archivo character varying(500),
    hoja_excel character varying(200),
    fila_excel integer,
    lote_carga character varying(200),
    fecha_carga date DEFAULT CURRENT_DATE,
    estado character varying(100),
    procesado boolean DEFAULT false,
    fecha_procesamiento timestamp without time zone,
    procesado_por integer,
    aspirante_id integer,
    apto boolean,
    puntaje_evaluacion numeric(10,4),
    contactado boolean DEFAULT false,
    fecha_contacto timestamp without time zone,
    respondio boolean DEFAULT false,
    observaciones text,
    activo boolean DEFAULT true,
    creado_en timestamp without time zone DEFAULT now(),
    actualizado_en timestamp without time zone DEFAULT now()
);


ALTER TABLE test.aspirantes_cargue OWNER TO whatsapp_db_vsfq_user;

--
-- TOC entry 380 (class 1259 OID 21524)
-- Name: aspirantes_encuesta_inicial; Type: TABLE; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE TABLE test.aspirantes_encuesta_inicial (
    id integer NOT NULL,
    aspirante_id bigint,
    respuestas_json jsonb,
    fecha_inicio timestamp without time zone,
    fecha_fin timestamp without time zone,
    completada boolean DEFAULT false NOT NULL,
    abandonada boolean DEFAULT false NOT NULL,
    preguntas_respondidas integer DEFAULT 0 NOT NULL,
    sincronizado boolean DEFAULT false NOT NULL,
    fecha_sincronizacion timestamp without time zone,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL
);


ALTER TABLE test.aspirantes_encuesta_inicial OWNER TO whatsapp_db_vsfq_user;

--
-- TOC entry 379 (class 1259 OID 21523)
-- Name: aspirantes_encuesta_inicial_id_seq; Type: SEQUENCE; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE SEQUENCE test.aspirantes_encuesta_inicial_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE test.aspirantes_encuesta_inicial_id_seq OWNER TO whatsapp_db_vsfq_user;

--
-- TOC entry 4496 (class 0 OID 0)
-- Dependencies: 379
-- Name: aspirantes_encuesta_inicial_id_seq; Type: SEQUENCE OWNED BY; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER SEQUENCE test.aspirantes_encuesta_inicial_id_seq OWNED BY test.aspirantes_encuesta_inicial.id;


--
-- TOC entry 376 (class 1259 OID 21506)
-- Name: aspirantes_estado_historial; Type: TABLE; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE TABLE test.aspirantes_estado_historial (
    id integer NOT NULL,
    aspirante_id integer NOT NULL,
    estado_id integer NOT NULL,
    fecha_cambio timestamp without time zone DEFAULT now() NOT NULL,
    usuario_id integer,
    origen_cambio character varying(50),
    observacion character varying(300),
    created_at timestamp without time zone DEFAULT now()
);


ALTER TABLE test.aspirantes_estado_historial OWNER TO whatsapp_db_vsfq_user;

--
-- TOC entry 375 (class 1259 OID 21505)
-- Name: aspirantes_estado_historial_id_seq; Type: SEQUENCE; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE SEQUENCE test.aspirantes_estado_historial_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE test.aspirantes_estado_historial_id_seq OWNER TO whatsapp_db_vsfq_user;

--
-- TOC entry 4497 (class 0 OID 0)
-- Dependencies: 375
-- Name: aspirantes_estado_historial_id_seq; Type: SEQUENCE OWNED BY; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER SEQUENCE test.aspirantes_estado_historial_id_seq OWNED BY test.aspirantes_estado_historial.id;


--
-- TOC entry 270 (class 1259 OID 19469)
-- Name: aspirantes_estados; Type: TABLE; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE TABLE test.aspirantes_estados (
    id integer DEFAULT nextval('public.estados_creador_id_seq'::regclass) NOT NULL,
    nombre character varying(100) NOT NULL
);


ALTER TABLE test.aspirantes_estados OWNER TO whatsapp_db_vsfq_user;

--
-- TOC entry 272 (class 1259 OID 19510)
-- Name: aspirantes_perfil; Type: TABLE; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE TABLE test.aspirantes_perfil (
    id integer DEFAULT nextval('public.perfil_creador1_id_seq'::regclass) NOT NULL,
    usuario character varying(100),
    aspirante_id integer,
    edad integer,
    genero character varying(50),
    pais integer,
    ciudad character varying(200),
    zona_horaria character varying(100),
    seguidores integer DEFAULT 0,
    siguiendo integer DEFAULT 0,
    videos integer DEFAULT 0,
    likes bigint DEFAULT 0,
    duracion_emisiones integer DEFAULT 0,
    dias_emisiones integer DEFAULT 0,
    apariencia integer DEFAULT 0,
    engagement integer DEFAULT 0,
    calidad_contenido integer DEFAULT 0,
    frecuencia_lives integer DEFAULT 0,
    biografia character varying(200),
    estado character varying(50) DEFAULT 'activo'::character varying,
    creado_en timestamp without time zone DEFAULT now(),
    actualizado_en timestamp without time zone DEFAULT now(),
    idioma character varying(100),
    campo_estudios character varying(200),
    estudios character varying,
    horario_preferido character varying,
    tiempo_disponible integer,
    experiencia_otras_plataformas jsonb,
    intereses jsonb,
    tipo_contenido jsonb,
    nombre character varying(100),
    potencial_estimado integer,
    experiencia_otras_plataformas_otro_nombre character varying(20),
    actividad_actual integer,
    biografia_sugerida character varying(600),
    usuario_evaluador_inicial integer,
    fecha_evaluacion_inicial timestamp without time zone,
    estado_evaluacion character varying(20),
    apto boolean DEFAULT false,
    observaciones_finales character varying(200),
    usuario_evalua text,
    telefono character varying(50),
    fecha_actualizacion timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    eval_foto integer,
    eval_biografia integer,
    metadata_videos integer,
    intencion_trabajo integer,
    experiencia_lives integer,
    experiencia_tiktok_live integer,
    pais_texto character varying(50)
);


ALTER TABLE test.aspirantes_perfil OWNER TO whatsapp_db_vsfq_user;

--
-- TOC entry 284 (class 1259 OID 20075)
-- Name: configuracion_agencia; Type: TABLE; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE TABLE test.configuracion_agencia (
    clave character varying(80) NOT NULL,
    valor text NOT NULL,
    actualizado_en timestamp without time zone DEFAULT now()
);


ALTER TABLE test.configuracion_agencia OWNER TO whatsapp_db_vsfq_user;

--
-- TOC entry 404 (class 1259 OID 22033)
-- Name: creadores; Type: TABLE; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE TABLE test.creadores (
    id integer NOT NULL,
    aspirante_id integer,
    nombre character varying(100),
    usuario_tiktok character varying(50),
    email character varying(200),
    telefono character varying(50),
    foto character varying(255),
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone DEFAULT now(),
    creador_tiktok_id character varying(255),
    estado_id integer NOT NULL,
    categoria_id integer,
    arquetipo_id integer,
    zona_horaria character varying(100)
);


ALTER TABLE test.creadores OWNER TO whatsapp_db_vsfq_user;

--
-- TOC entry 4498 (class 0 OID 0)
-- Dependencies: 404
-- Name: COLUMN creadores.zona_horaria; Type: COMMENT; Schema: test; Owner: whatsapp_db_vsfq_user
--

COMMENT ON COLUMN test.creadores.zona_horaria IS 'Zona horaria IANA del creador, por ejemplo America/Bogota, America/Mexico_City o Europe/Madrid';


--
-- TOC entry 439 (class 1259 OID 22421)
-- Name: creadores_arquetipo; Type: TABLE; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE TABLE test.creadores_arquetipo (
    id integer NOT NULL,
    codigo character varying(80) NOT NULL,
    nombre character varying(100) NOT NULL,
    descripcion_operativa text,
    estrategia_json jsonb,
    activo boolean DEFAULT true,
    orden integer,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


ALTER TABLE test.creadores_arquetipo OWNER TO whatsapp_db_vsfq_user;

--
-- TOC entry 438 (class 1259 OID 22420)
-- Name: creadores_arquetipo_id_seq; Type: SEQUENCE; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE SEQUENCE test.creadores_arquetipo_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE test.creadores_arquetipo_id_seq OWNER TO whatsapp_db_vsfq_user;

--
-- TOC entry 4499 (class 0 OID 0)
-- Dependencies: 438
-- Name: creadores_arquetipo_id_seq; Type: SEQUENCE OWNED BY; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER SEQUENCE test.creadores_arquetipo_id_seq OWNED BY test.creadores_arquetipo.id;


--
-- TOC entry 459 (class 1259 OID 22769)
-- Name: creadores_capacitaciones; Type: TABLE; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE TABLE test.creadores_capacitaciones (
    id_capacitacion integer NOT NULL,
    nombre character varying(150) NOT NULL,
    descripcion text,
    categoria character varying(100),
    obligatoria boolean DEFAULT true NOT NULL,
    activa boolean DEFAULT true NOT NULL,
    orden integer DEFAULT 1 NOT NULL,
    fecha_creacion timestamp without time zone DEFAULT now(),
    fecha_actualizacion timestamp without time zone DEFAULT now()
);


ALTER TABLE test.creadores_capacitaciones OWNER TO whatsapp_db_vsfq_user;

--
-- TOC entry 458 (class 1259 OID 22768)
-- Name: creadores_capacitaciones_id_capacitacion_seq; Type: SEQUENCE; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE SEQUENCE test.creadores_capacitaciones_id_capacitacion_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE test.creadores_capacitaciones_id_capacitacion_seq OWNER TO whatsapp_db_vsfq_user;

--
-- TOC entry 4500 (class 0 OID 0)
-- Dependencies: 458
-- Name: creadores_capacitaciones_id_capacitacion_seq; Type: SEQUENCE OWNED BY; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER SEQUENCE test.creadores_capacitaciones_id_capacitacion_seq OWNED BY test.creadores_capacitaciones.id_capacitacion;


--
-- TOC entry 461 (class 1259 OID 22785)
-- Name: creadores_capacitaciones_seguimiento; Type: TABLE; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE TABLE test.creadores_capacitaciones_seguimiento (
    id_seguimiento integer NOT NULL,
    creador_id integer,
    creador_tiktok_id character varying(255),
    usuario_tiktok character varying(100),
    manager character varying(200),
    grupo character varying(150),
    id_capacitacion integer NOT NULL,
    estado character varying(30) DEFAULT 'pendiente'::character varying NOT NULL,
    fecha_realizacion date,
    observacion text,
    actualizado_por integer,
    fecha_creacion timestamp without time zone DEFAULT now(),
    fecha_actualizacion timestamp without time zone DEFAULT now(),
    CONSTRAINT chk_capacitacion_estado CHECK (((estado)::text = ANY ((ARRAY['pendiente'::character varying, 'realizada'::character varying, 'no_aplica'::character varying])::text[])))
);


ALTER TABLE test.creadores_capacitaciones_seguimiento OWNER TO whatsapp_db_vsfq_user;

--
-- TOC entry 460 (class 1259 OID 22784)
-- Name: creadores_capacitaciones_seguimiento_id_seguimiento_seq; Type: SEQUENCE; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE SEQUENCE test.creadores_capacitaciones_seguimiento_id_seguimiento_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE test.creadores_capacitaciones_seguimiento_id_seguimiento_seq OWNER TO whatsapp_db_vsfq_user;

--
-- TOC entry 4501 (class 0 OID 0)
-- Dependencies: 460
-- Name: creadores_capacitaciones_seguimiento_id_seguimiento_seq; Type: SEQUENCE OWNED BY; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER SEQUENCE test.creadores_capacitaciones_seguimiento_id_seguimiento_seq OWNED BY test.creadores_capacitaciones_seguimiento.id_seguimiento;


--
-- TOC entry 426 (class 1259 OID 22311)
-- Name: creadores_categoria; Type: TABLE; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE TABLE test.creadores_categoria (
    id integer NOT NULL,
    nombre character varying(50) NOT NULL,
    meta_diamantes_objetivo integer,
    descripcion character varying(300),
    orden integer,
    activa boolean DEFAULT true,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


ALTER TABLE test.creadores_categoria OWNER TO whatsapp_db_vsfq_user;

--
-- TOC entry 425 (class 1259 OID 22310)
-- Name: creadores_categoria_id_seq; Type: SEQUENCE; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE SEQUENCE test.creadores_categoria_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE test.creadores_categoria_id_seq OWNER TO whatsapp_db_vsfq_user;

--
-- TOC entry 4502 (class 0 OID 0)
-- Dependencies: 425
-- Name: creadores_categoria_id_seq; Type: SEQUENCE OWNED BY; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER SEQUENCE test.creadores_categoria_id_seq OWNED BY test.creadores_categoria.id;


--
-- TOC entry 406 (class 1259 OID 22048)
-- Name: creadores_detalle; Type: TABLE; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE TABLE test.creadores_detalle (
    id integer NOT NULL,
    creador_id integer NOT NULL,
    manager_id integer,
    horario_lives character varying(30),
    tiempo_disponible integer,
    fecha_incorporacion date,
    fecha_graduacion date,
    seguidores integer DEFAULT 0,
    videos integer DEFAULT 0,
    me_gusta integer DEFAULT 0,
    diamantes integer DEFAULT 0,
    horas_live integer DEFAULT 0,
    numero_partidas integer DEFAULT 0,
    dias_emision integer DEFAULT 0,
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone DEFAULT now()
);


ALTER TABLE test.creadores_detalle OWNER TO whatsapp_db_vsfq_user;

--
-- TOC entry 405 (class 1259 OID 22047)
-- Name: creadores_detalle_id_seq; Type: SEQUENCE; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE SEQUENCE test.creadores_detalle_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE test.creadores_detalle_id_seq OWNER TO whatsapp_db_vsfq_user;

--
-- TOC entry 4503 (class 0 OID 0)
-- Dependencies: 405
-- Name: creadores_detalle_id_seq; Type: SEQUENCE OWNED BY; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER SEQUENCE test.creadores_detalle_id_seq OWNED BY test.creadores_detalle.id;


--
-- TOC entry 386 (class 1259 OID 21581)
-- Name: creadores_encuesta_inicial; Type: TABLE; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE TABLE test.creadores_encuesta_inicial (
    id integer NOT NULL,
    creador_id bigint,
    respuestas_json jsonb,
    fecha_inicio timestamp without time zone,
    fecha_fin timestamp without time zone,
    completada boolean DEFAULT false NOT NULL,
    abandonada boolean DEFAULT false NOT NULL,
    preguntas_respondidas integer DEFAULT 0 NOT NULL,
    sincronizado boolean DEFAULT false NOT NULL,
    fecha_sincronizacion timestamp without time zone,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL
);


ALTER TABLE test.creadores_encuesta_inicial OWNER TO whatsapp_db_vsfq_user;

--
-- TOC entry 385 (class 1259 OID 21580)
-- Name: creadores_encuesta_inicial_id_seq; Type: SEQUENCE; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE SEQUENCE test.creadores_encuesta_inicial_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE test.creadores_encuesta_inicial_id_seq OWNER TO whatsapp_db_vsfq_user;

--
-- TOC entry 4504 (class 0 OID 0)
-- Dependencies: 385
-- Name: creadores_encuesta_inicial_id_seq; Type: SEQUENCE OWNED BY; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER SEQUENCE test.creadores_encuesta_inicial_id_seq OWNED BY test.creadores_encuesta_inicial.id;


--
-- TOC entry 424 (class 1259 OID 22283)
-- Name: creadores_estados; Type: TABLE; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE TABLE test.creadores_estados (
    id integer NOT NULL,
    nombre character varying(50) NOT NULL,
    descripcion character varying(200),
    activo boolean DEFAULT true NOT NULL,
    orden integer DEFAULT 0 NOT NULL,
    creado_en timestamp without time zone DEFAULT now() NOT NULL
);


ALTER TABLE test.creadores_estados OWNER TO whatsapp_db_vsfq_user;

--
-- TOC entry 423 (class 1259 OID 22282)
-- Name: creadores_estados_id_seq; Type: SEQUENCE; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER TABLE test.creadores_estados ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME test.creadores_estados_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- TOC entry 403 (class 1259 OID 22032)
-- Name: creadores_id_seq; Type: SEQUENCE; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE SEQUENCE test.creadores_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE test.creadores_id_seq OWNER TO whatsapp_db_vsfq_user;

--
-- TOC entry 4505 (class 0 OID 0)
-- Dependencies: 403
-- Name: creadores_id_seq; Type: SEQUENCE OWNED BY; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER SEQUENCE test.creadores_id_seq OWNED BY test.creadores.id;


--
-- TOC entry 416 (class 1259 OID 22190)
-- Name: creadores_insights_mensuales; Type: TABLE; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE TABLE test.creadores_insights_mensuales (
    id integer NOT NULL,
    creador_id integer NOT NULL,
    id_reporte integer NOT NULL,
    periodo_inicio date NOT NULL,
    periodo_fin date NOT NULL,
    nivel_rendimiento character varying(50),
    alerta_principal character varying(100),
    insight_general character varying(600),
    recomendacion_1 character varying(600),
    recomendacion_2 character varying(600),
    recomendacion_3 character varying(600),
    created_at timestamp without time zone DEFAULT now()
);


ALTER TABLE test.creadores_insights_mensuales OWNER TO whatsapp_db_vsfq_user;

--
-- TOC entry 415 (class 1259 OID 22189)
-- Name: creadores_insights_mensuales_id_seq; Type: SEQUENCE; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE SEQUENCE test.creadores_insights_mensuales_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE test.creadores_insights_mensuales_id_seq OWNER TO whatsapp_db_vsfq_user;

--
-- TOC entry 4506 (class 0 OID 0)
-- Dependencies: 415
-- Name: creadores_insights_mensuales_id_seq; Type: SEQUENCE OWNED BY; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER SEQUENCE test.creadores_insights_mensuales_id_seq OWNED BY test.creadores_insights_mensuales.id;


--
-- TOC entry 420 (class 1259 OID 22220)
-- Name: creadores_metas_mensuales; Type: TABLE; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE TABLE test.creadores_metas_mensuales (
    id integer NOT NULL,
    creador_id integer NOT NULL,
    periodo_inicio date NOT NULL,
    periodo_fin date NOT NULL,
    meta_diamantes integer,
    meta_horas_live integer,
    meta_dias_validos integer,
    meta_emisiones integer,
    meta_nuevos_seguidores integer,
    fuente character varying(50) DEFAULT 'sistema'::character varying,
    created_at timestamp without time zone DEFAULT now()
);


ALTER TABLE test.creadores_metas_mensuales OWNER TO whatsapp_db_vsfq_user;

--
-- TOC entry 419 (class 1259 OID 22219)
-- Name: creadores_metas_mensuales_id_seq; Type: SEQUENCE; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE SEQUENCE test.creadores_metas_mensuales_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE test.creadores_metas_mensuales_id_seq OWNER TO whatsapp_db_vsfq_user;

--
-- TOC entry 4507 (class 0 OID 0)
-- Dependencies: 419
-- Name: creadores_metas_mensuales_id_seq; Type: SEQUENCE OWNED BY; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER SEQUENCE test.creadores_metas_mensuales_id_seq OWNED BY test.creadores_metas_mensuales.id;


--
-- TOC entry 391 (class 1259 OID 21816)
-- Name: creadores_perfil_categoria; Type: TABLE; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE TABLE test.creadores_perfil_categoria (
    id integer NOT NULL,
    nombre character varying(100) NOT NULL,
    nombre_natural character varying(100),
    descripcion character varying(300),
    orden integer,
    activa boolean DEFAULT true,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    tipo character varying(30) DEFAULT 'DIAGNOSTICO'::character varying
);


ALTER TABLE test.creadores_perfil_categoria OWNER TO whatsapp_db_vsfq_user;

--
-- TOC entry 390 (class 1259 OID 21815)
-- Name: creadores_perfil_categoria_id_seq; Type: SEQUENCE; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE SEQUENCE test.creadores_perfil_categoria_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE test.creadores_perfil_categoria_id_seq OWNER TO whatsapp_db_vsfq_user;

--
-- TOC entry 4508 (class 0 OID 0)
-- Dependencies: 390
-- Name: creadores_perfil_categoria_id_seq; Type: SEQUENCE OWNED BY; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER SEQUENCE test.creadores_perfil_categoria_id_seq OWNED BY test.creadores_perfil_categoria.id;


--
-- TOC entry 396 (class 1259 OID 21847)
-- Name: creadores_perfil_respuesta; Type: TABLE; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE TABLE test.creadores_perfil_respuesta (
    id integer NOT NULL,
    creador_id integer NOT NULL,
    variable_id integer NOT NULL,
    valor_integer integer,
    valor_id integer,
    valor_numeric numeric,
    valor_texto text,
    valor_json jsonb,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


ALTER TABLE test.creadores_perfil_respuesta OWNER TO whatsapp_db_vsfq_user;

--
-- TOC entry 395 (class 1259 OID 21846)
-- Name: creadores_perfil_respuesta_id_seq; Type: SEQUENCE; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE SEQUENCE test.creadores_perfil_respuesta_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE test.creadores_perfil_respuesta_id_seq OWNER TO whatsapp_db_vsfq_user;

--
-- TOC entry 4509 (class 0 OID 0)
-- Dependencies: 395
-- Name: creadores_perfil_respuesta_id_seq; Type: SEQUENCE OWNED BY; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER SEQUENCE test.creadores_perfil_respuesta_id_seq OWNED BY test.creadores_perfil_respuesta.id;


--
-- TOC entry 394 (class 1259 OID 21839)
-- Name: creadores_perfil_valor; Type: TABLE; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE TABLE test.creadores_perfil_valor (
    id integer DEFAULT nextval('test.modelo_variable_valor_id_seq'::regclass) NOT NULL,
    variable_id integer NOT NULL,
    min_val numeric,
    max_val numeric,
    score integer NOT NULL,
    label character varying(80) NOT NULL,
    nivel character varying(20),
    orden integer,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    valor_padre_id integer
);


ALTER TABLE test.creadores_perfil_valor OWNER TO whatsapp_db_vsfq_user;

--
-- TOC entry 393 (class 1259 OID 21827)
-- Name: creadores_perfil_variable; Type: TABLE; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE TABLE test.creadores_perfil_variable (
    id integer NOT NULL,
    categoria_id integer,
    nombre character varying(100),
    campo_db character varying(100),
    peso_variable numeric(5,2) DEFAULT 0,
    tipo character varying(50),
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    encuesta_id integer,
    activa boolean DEFAULT true,
    tipo_form character varying(15),
    texto character varying(300),
    orden integer,
    migrado boolean DEFAULT false,
    nombre_natural character varying(150)
);


ALTER TABLE test.creadores_perfil_variable OWNER TO whatsapp_db_vsfq_user;

--
-- TOC entry 392 (class 1259 OID 21826)
-- Name: creadores_perfil_variable_id_seq; Type: SEQUENCE; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE SEQUENCE test.creadores_perfil_variable_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE test.creadores_perfil_variable_id_seq OWNER TO whatsapp_db_vsfq_user;

--
-- TOC entry 4510 (class 0 OID 0)
-- Dependencies: 392
-- Name: creadores_perfil_variable_id_seq; Type: SEQUENCE OWNED BY; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER SEQUENCE test.creadores_perfil_variable_id_seq OWNED BY test.creadores_perfil_variable.id;


--
-- TOC entry 429 (class 1259 OID 22338)
-- Name: creadores_performance_acciones; Type: TABLE; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE TABLE test.creadores_performance_acciones (
    id integer NOT NULL,
    seguimiento_id integer NOT NULL,
    tipo_accion character varying(100) NOT NULL,
    titulo character varying(200),
    descripcion text,
    prioridad character varying(20) DEFAULT 'media'::character varying,
    estado character varying(30) DEFAULT 'pendiente'::character varying,
    fecha_compromiso date,
    fecha_cumplimiento date,
    creado_por integer,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


ALTER TABLE test.creadores_performance_acciones OWNER TO whatsapp_db_vsfq_user;

--
-- TOC entry 428 (class 1259 OID 22337)
-- Name: creadores_performance_acciones_id_seq; Type: SEQUENCE; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE SEQUENCE test.creadores_performance_acciones_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE test.creadores_performance_acciones_id_seq OWNER TO whatsapp_db_vsfq_user;

--
-- TOC entry 4511 (class 0 OID 0)
-- Dependencies: 428
-- Name: creadores_performance_acciones_id_seq; Type: SEQUENCE OWNED BY; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER SEQUENCE test.creadores_performance_acciones_id_seq OWNED BY test.creadores_performance_acciones.id;


--
-- TOC entry 431 (class 1259 OID 22356)
-- Name: creadores_performance_alertas; Type: TABLE; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE TABLE test.creadores_performance_alertas (
    id integer NOT NULL,
    creador_id integer NOT NULL,
    id_reporte integer,
    tipo_alerta character varying(100),
    nivel_alerta character varying(20),
    titulo character varying(200),
    descripcion text,
    origen character varying(50) DEFAULT 'ia'::character varying,
    estado character varying(30) DEFAULT 'activa'::character varying,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    resolved_at timestamp without time zone
);


ALTER TABLE test.creadores_performance_alertas OWNER TO whatsapp_db_vsfq_user;

--
-- TOC entry 430 (class 1259 OID 22355)
-- Name: creadores_performance_alertas_id_seq; Type: SEQUENCE; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE SEQUENCE test.creadores_performance_alertas_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE test.creadores_performance_alertas_id_seq OWNER TO whatsapp_db_vsfq_user;

--
-- TOC entry 4512 (class 0 OID 0)
-- Dependencies: 430
-- Name: creadores_performance_alertas_id_seq; Type: SEQUENCE OWNED BY; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER SEQUENCE test.creadores_performance_alertas_id_seq OWNED BY test.creadores_performance_alertas.id;


--
-- TOC entry 449 (class 1259 OID 22646)
-- Name: creadores_performance_objetivos; Type: TABLE; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE TABLE test.creadores_performance_objetivos (
    id_objetivo integer NOT NULL,
    nivel_aplicacion character varying(20) NOT NULL,
    creador_tiktok_id character varying(255),
    creador_id integer,
    manager character varying(200),
    grupo character varying(150),
    id_rango integer,
    objetivo_diamantes_mes integer,
    objetivo_diamantes_semana integer,
    objetivo_horas_mes numeric(10,2),
    objetivo_horas_semana numeric(10,2),
    objetivo_dias_mes integer,
    objetivo_dias_semana integer,
    fecha_inicio date DEFAULT CURRENT_DATE NOT NULL,
    fecha_fin date,
    activo boolean DEFAULT true NOT NULL,
    fecha_creacion timestamp without time zone DEFAULT now(),
    CONSTRAINT chk_performance_objetivo_fechas CHECK (((fecha_fin IS NULL) OR (fecha_fin >= fecha_inicio))),
    CONSTRAINT chk_performance_objetivo_nivel CHECK (((nivel_aplicacion)::text = ANY ((ARRAY['agencia'::character varying, 'grupo'::character varying, 'manager'::character varying, 'creador'::character varying, 'rango'::character varying])::text[])))
);


ALTER TABLE test.creadores_performance_objetivos OWNER TO whatsapp_db_vsfq_user;

--
-- TOC entry 448 (class 1259 OID 22645)
-- Name: creadores_performance_objetivos_id_objetivo_seq; Type: SEQUENCE; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE SEQUENCE test.creadores_performance_objetivos_id_objetivo_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE test.creadores_performance_objetivos_id_objetivo_seq OWNER TO whatsapp_db_vsfq_user;

--
-- TOC entry 4513 (class 0 OID 0)
-- Dependencies: 448
-- Name: creadores_performance_objetivos_id_objetivo_seq; Type: SEQUENCE OWNED BY; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER SEQUENCE test.creadores_performance_objetivos_id_objetivo_seq OWNED BY test.creadores_performance_objetivos.id_objetivo;


--
-- TOC entry 457 (class 1259 OID 22735)
-- Name: creadores_performance_observaciones; Type: TABLE; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE TABLE test.creadores_performance_observaciones (
    id_observacion integer NOT NULL,
    creador_tiktok_id character varying(255) NOT NULL,
    creador_id integer,
    usuario_tiktok character varying(100),
    periodo_inicio date NOT NULL,
    periodo_fin date NOT NULL,
    manager character varying(200),
    grupo character varying(150),
    estado_manual character varying(100),
    observacion text,
    recomendacion text,
    creada_por integer,
    fecha_creacion timestamp without time zone DEFAULT now(),
    fecha_actualizacion timestamp without time zone DEFAULT now(),
    activo boolean DEFAULT true NOT NULL
);


ALTER TABLE test.creadores_performance_observaciones OWNER TO whatsapp_db_vsfq_user;

--
-- TOC entry 456 (class 1259 OID 22734)
-- Name: creadores_performance_observaciones_id_observacion_seq; Type: SEQUENCE; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE SEQUENCE test.creadores_performance_observaciones_id_observacion_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE test.creadores_performance_observaciones_id_observacion_seq OWNER TO whatsapp_db_vsfq_user;

--
-- TOC entry 4514 (class 0 OID 0)
-- Dependencies: 456
-- Name: creadores_performance_observaciones_id_observacion_seq; Type: SEQUENCE OWNED BY; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER SEQUENCE test.creadores_performance_observaciones_id_observacion_seq OWNED BY test.creadores_performance_observaciones.id_observacion;


--
-- TOC entry 445 (class 1259 OID 22614)
-- Name: creadores_performance_rangos_diamantes; Type: TABLE; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE TABLE test.creadores_performance_rangos_diamantes (
    id_rango integer NOT NULL,
    codigo_rango character varying(50) NOT NULL,
    nombre_rango character varying(100) NOT NULL,
    descripcion text,
    diamantes_min integer DEFAULT 0 NOT NULL,
    diamantes_max integer,
    objetivo_diamantes_mes integer,
    objetivo_diamantes_semana integer,
    objetivo_horas_mes numeric(10,2),
    objetivo_horas_semana numeric(10,2),
    objetivo_dias_mes integer,
    objetivo_dias_semana integer,
    orden integer DEFAULT 1 NOT NULL,
    color_hex character varying(20),
    activo boolean DEFAULT true NOT NULL,
    fecha_creacion timestamp without time zone DEFAULT now(),
    CONSTRAINT chk_rangos_diamantes_rango CHECK (((diamantes_max IS NULL) OR (diamantes_min < diamantes_max)))
);


ALTER TABLE test.creadores_performance_rangos_diamantes OWNER TO whatsapp_db_vsfq_user;

--
-- TOC entry 444 (class 1259 OID 22613)
-- Name: creadores_performance_rangos_diamantes_id_rango_seq; Type: SEQUENCE; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE SEQUENCE test.creadores_performance_rangos_diamantes_id_rango_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE test.creadores_performance_rangos_diamantes_id_rango_seq OWNER TO whatsapp_db_vsfq_user;

--
-- TOC entry 4515 (class 0 OID 0)
-- Dependencies: 444
-- Name: creadores_performance_rangos_diamantes_id_rango_seq; Type: SEQUENCE OWNED BY; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER SEQUENCE test.creadores_performance_rangos_diamantes_id_rango_seq OWNED BY test.creadores_performance_rangos_diamantes.id_rango;


--
-- TOC entry 433 (class 1259 OID 22368)
-- Name: creadores_performance_recomendaciones; Type: TABLE; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE TABLE test.creadores_performance_recomendaciones (
    id integer NOT NULL,
    creador_id integer NOT NULL,
    id_reporte integer,
    categoria character varying(100),
    prioridad character varying(20),
    recomendacion text NOT NULL,
    justificacion text,
    aplicada boolean DEFAULT false,
    aplicada_at timestamp without time zone,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


ALTER TABLE test.creadores_performance_recomendaciones OWNER TO whatsapp_db_vsfq_user;

--
-- TOC entry 432 (class 1259 OID 22367)
-- Name: creadores_performance_recomendaciones_id_seq; Type: SEQUENCE; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE SEQUENCE test.creadores_performance_recomendaciones_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE test.creadores_performance_recomendaciones_id_seq OWNER TO whatsapp_db_vsfq_user;

--
-- TOC entry 4516 (class 0 OID 0)
-- Dependencies: 432
-- Name: creadores_performance_recomendaciones_id_seq; Type: SEQUENCE OWNED BY; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER SEQUENCE test.creadores_performance_recomendaciones_id_seq OWNED BY test.creadores_performance_recomendaciones.id;


--
-- TOC entry 447 (class 1259 OID 22630)
-- Name: creadores_performance_reglas_estado; Type: TABLE; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE TABLE test.creadores_performance_reglas_estado (
    id_regla integer NOT NULL,
    tipo_regla character varying(50) NOT NULL,
    codigo_estado character varying(50) NOT NULL,
    nombre_estado character varying(100) NOT NULL,
    descripcion text,
    tipo_periodo character varying(20) DEFAULT 'semanal'::character varying NOT NULL,
    valor_min numeric(14,2),
    valor_max numeric(14,2),
    prioridad integer DEFAULT 10 NOT NULL,
    color_hex character varying(20),
    activo boolean DEFAULT true NOT NULL,
    fecha_creacion timestamp without time zone DEFAULT now(),
    CONSTRAINT chk_reglas_estado_rango CHECK (((valor_min IS NULL) OR (valor_max IS NULL) OR (valor_min < valor_max))),
    CONSTRAINT chk_reglas_estado_tipo_periodo CHECK (((tipo_periodo)::text = ANY ((ARRAY['semanal'::character varying, 'mensual'::character varying, 'otro'::character varying, 'todos'::character varying])::text[])))
);


ALTER TABLE test.creadores_performance_reglas_estado OWNER TO whatsapp_db_vsfq_user;

--
-- TOC entry 446 (class 1259 OID 22629)
-- Name: creadores_performance_reglas_estado_id_regla_seq; Type: SEQUENCE; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE SEQUENCE test.creadores_performance_reglas_estado_id_regla_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE test.creadores_performance_reglas_estado_id_regla_seq OWNER TO whatsapp_db_vsfq_user;

--
-- TOC entry 4517 (class 0 OID 0)
-- Dependencies: 446
-- Name: creadores_performance_reglas_estado_id_regla_seq; Type: SEQUENCE OWNED BY; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER SEQUENCE test.creadores_performance_reglas_estado_id_regla_seq OWNED BY test.creadores_performance_reglas_estado.id_regla;


--
-- TOC entry 437 (class 1259 OID 22389)
-- Name: creadores_performance_resumen; Type: TABLE; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE TABLE test.creadores_performance_resumen (
    id integer NOT NULL,
    creador_id integer NOT NULL,
    periodo_inicio date NOT NULL,
    periodo_fin date NOT NULL,
    diamantes integer,
    horas_live numeric(10,2),
    dias_validos integer,
    emisiones integer,
    nuevos_seguidores integer,
    cumplimiento_general numeric(5,2),
    tendencia character varying(30),
    nivel_rendimiento character varying(50),
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


ALTER TABLE test.creadores_performance_resumen OWNER TO whatsapp_db_vsfq_user;

--
-- TOC entry 436 (class 1259 OID 22388)
-- Name: creadores_performance_resumen_id_seq; Type: SEQUENCE; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE SEQUENCE test.creadores_performance_resumen_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE test.creadores_performance_resumen_id_seq OWNER TO whatsapp_db_vsfq_user;

--
-- TOC entry 4518 (class 0 OID 0)
-- Dependencies: 436
-- Name: creadores_performance_resumen_id_seq; Type: SEQUENCE OWNED BY; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER SEQUENCE test.creadores_performance_resumen_id_seq OWNED BY test.creadores_performance_resumen.id;


--
-- TOC entry 435 (class 1259 OID 22379)
-- Name: creadores_performance_score; Type: TABLE; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE TABLE test.creadores_performance_score (
    id integer NOT NULL,
    creador_id integer NOT NULL,
    id_reporte integer,
    score_general numeric(5,2),
    nivel_rendimiento character varying(50),
    riesgo_abandono character varying(30),
    probabilidad_crecimiento numeric(5,2),
    consistencia_score numeric(5,2),
    monetizacion_score numeric(5,2),
    engagement_score numeric(5,2),
    observacion_ia text,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


ALTER TABLE test.creadores_performance_score OWNER TO whatsapp_db_vsfq_user;

--
-- TOC entry 434 (class 1259 OID 22378)
-- Name: creadores_performance_score_id_seq; Type: SEQUENCE; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE SEQUENCE test.creadores_performance_score_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE test.creadores_performance_score_id_seq OWNER TO whatsapp_db_vsfq_user;

--
-- TOC entry 4519 (class 0 OID 0)
-- Dependencies: 434
-- Name: creadores_performance_score_id_seq; Type: SEQUENCE OWNED BY; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER SEQUENCE test.creadores_performance_score_id_seq OWNED BY test.creadores_performance_score.id;


--
-- TOC entry 274 (class 1259 OID 19557)
-- Name: creadores_performance_seguimiento; Type: TABLE; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE TABLE test.creadores_performance_seguimiento (
    id integer DEFAULT nextval('public.seguimiento_creadores_id_seq'::regclass) NOT NULL,
    creador_id integer,
    manager_id integer,
    fecha_seguimiento date,
    observaciones_manager text,
    resumen_compromisos text
);


ALTER TABLE test.creadores_performance_seguimiento OWNER TO whatsapp_db_vsfq_user;

--
-- TOC entry 451 (class 1259 OID 22670)
-- Name: creadores_performance_tablero_cortes; Type: TABLE; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE TABLE test.creadores_performance_tablero_cortes (
    id_corte integer NOT NULL,
    periodo_corte_inicio date,
    periodo_corte_fin date NOT NULL,
    semanas_mostradas integer DEFAULT 8 NOT NULL,
    estado character varying(30) DEFAULT 'activo'::character varying NOT NULL,
    fecha_calculo timestamp without time zone DEFAULT now(),
    observaciones text,
    CONSTRAINT chk_tablero_cortes_estado CHECK (((estado)::text = ANY ((ARRAY['activo'::character varying, 'historico'::character varying, 'error'::character varying])::text[]))),
    CONSTRAINT chk_tablero_cortes_semanas CHECK ((semanas_mostradas = ANY (ARRAY[4, 8])))
);


ALTER TABLE test.creadores_performance_tablero_cortes OWNER TO whatsapp_db_vsfq_user;

--
-- TOC entry 450 (class 1259 OID 22669)
-- Name: creadores_performance_tablero_cortes_id_corte_seq; Type: SEQUENCE; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE SEQUENCE test.creadores_performance_tablero_cortes_id_corte_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE test.creadores_performance_tablero_cortes_id_corte_seq OWNER TO whatsapp_db_vsfq_user;

--
-- TOC entry 4520 (class 0 OID 0)
-- Dependencies: 450
-- Name: creadores_performance_tablero_cortes_id_corte_seq; Type: SEQUENCE OWNED BY; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER SEQUENCE test.creadores_performance_tablero_cortes_id_corte_seq OWNED BY test.creadores_performance_tablero_cortes.id_corte;


--
-- TOC entry 453 (class 1259 OID 22686)
-- Name: creadores_performance_tablero_creadores; Type: TABLE; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE TABLE test.creadores_performance_tablero_creadores (
    id_tablero_creador integer NOT NULL,
    id_corte integer NOT NULL,
    creador_tiktok_id character varying(255) NOT NULL,
    creador_id integer,
    usuario_tiktok character varying(100),
    grupo character varying(150),
    manager_actual character varying(200),
    dias_desde_incorporacion integer,
    rango_codigo character varying(50),
    rango_nombre character varying(100),
    diamantes_ultimo_mes integer DEFAULT 0,
    horas_ultimo_mes numeric(10,2) DEFAULT 0,
    dias_ultimo_mes integer DEFAULT 0,
    objetivo_mensual integer,
    objetivo_semanal integer,
    objetivo_horas_mes numeric(10,2),
    objetivo_horas_semana numeric(10,2),
    objetivo_dias_mes integer,
    objetivo_dias_semana integer,
    variacion_ultima_semana_pct numeric(8,2),
    estado_general character varying(100),
    nivel_riesgo character varying(50),
    fecha_actualizacion timestamp without time zone DEFAULT now(),
    manager_id integer,
    estado_agencia character varying(50) DEFAULT 'activo'::character varying
);


ALTER TABLE test.creadores_performance_tablero_creadores OWNER TO whatsapp_db_vsfq_user;

--
-- TOC entry 452 (class 1259 OID 22685)
-- Name: creadores_performance_tablero_creadores_id_tablero_creador_seq; Type: SEQUENCE; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE SEQUENCE test.creadores_performance_tablero_creadores_id_tablero_creador_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE test.creadores_performance_tablero_creadores_id_tablero_creador_seq OWNER TO whatsapp_db_vsfq_user;

--
-- TOC entry 4521 (class 0 OID 0)
-- Dependencies: 452
-- Name: creadores_performance_tablero_creadores_id_tablero_creador_seq; Type: SEQUENCE OWNED BY; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER SEQUENCE test.creadores_performance_tablero_creadores_id_tablero_creador_seq OWNED BY test.creadores_performance_tablero_creadores.id_tablero_creador;


--
-- TOC entry 455 (class 1259 OID 22711)
-- Name: creadores_performance_tablero_semanas; Type: TABLE; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE TABLE test.creadores_performance_tablero_semanas (
    id_tablero_semana integer NOT NULL,
    id_tablero_creador integer NOT NULL,
    semana_orden integer NOT NULL,
    periodo_inicio date NOT NULL,
    periodo_fin date NOT NULL,
    diamantes integer DEFAULT 0,
    horas numeric(10,2) DEFAULT 0,
    dias integer DEFAULT 0,
    manager_semana character varying(200),
    estado_auto character varying(100),
    estado_manual character varying(100),
    variacion_diamantes_pct numeric(8,2),
    tiene_observacion boolean DEFAULT false NOT NULL,
    fecha_actualizacion timestamp without time zone DEFAULT now(),
    manager_id integer,
    estado_agencia character varying(50) DEFAULT 'activo'::character varying,
    CONSTRAINT chk_tablero_semana_orden CHECK (((semana_orden >= 1) AND (semana_orden <= 8)))
);


ALTER TABLE test.creadores_performance_tablero_semanas OWNER TO whatsapp_db_vsfq_user;

--
-- TOC entry 454 (class 1259 OID 22710)
-- Name: creadores_performance_tablero_semanas_id_tablero_semana_seq; Type: SEQUENCE; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE SEQUENCE test.creadores_performance_tablero_semanas_id_tablero_semana_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE test.creadores_performance_tablero_semanas_id_tablero_semana_seq OWNER TO whatsapp_db_vsfq_user;

--
-- TOC entry 4522 (class 0 OID 0)
-- Dependencies: 454
-- Name: creadores_performance_tablero_semanas_id_tablero_semana_seq; Type: SEQUENCE OWNED BY; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER SEQUENCE test.creadores_performance_tablero_semanas_id_tablero_semana_seq OWNED BY test.creadores_performance_tablero_semanas.id_tablero_semana;


--
-- TOC entry 443 (class 1259 OID 22592)
-- Name: creadores_reporte_importaciones; Type: TABLE; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE TABLE test.creadores_reporte_importaciones (
    id_importacion integer NOT NULL,
    archivo_nombre character varying(255),
    archivo_origen character varying(255),
    periodo_inicio date NOT NULL,
    periodo_fin date NOT NULL,
    tipo_periodo character varying(20) DEFAULT 'semanal'::character varying NOT NULL,
    total_filas integer,
    total_creadores integer,
    estado character varying(30) DEFAULT 'procesado'::character varying NOT NULL,
    observaciones text,
    cargado_por integer,
    fecha_carga timestamp without time zone DEFAULT now(),
    metadata_json jsonb DEFAULT '{}'::jsonb,
    CONSTRAINT chk_reporte_importaciones_estado CHECK (((estado)::text = ANY ((ARRAY['pendiente'::character varying, 'procesado'::character varying, 'error'::character varying, 'validado'::character varying])::text[]))),
    CONSTRAINT chk_reporte_importaciones_tipo_periodo CHECK (((tipo_periodo)::text = ANY ((ARRAY['semanal'::character varying, 'mensual'::character varying, 'otro'::character varying])::text[])))
);


ALTER TABLE test.creadores_reporte_importaciones OWNER TO whatsapp_db_vsfq_user;

--
-- TOC entry 442 (class 1259 OID 22591)
-- Name: creadores_reporte_importaciones_id_importacion_seq; Type: SEQUENCE; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE SEQUENCE test.creadores_reporte_importaciones_id_importacion_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE test.creadores_reporte_importaciones_id_importacion_seq OWNER TO whatsapp_db_vsfq_user;

--
-- TOC entry 4523 (class 0 OID 0)
-- Dependencies: 442
-- Name: creadores_reporte_importaciones_id_importacion_seq; Type: SEQUENCE OWNED BY; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER SEQUENCE test.creadores_reporte_importaciones_id_importacion_seq OWNED BY test.creadores_reporte_importaciones.id_importacion;


--
-- TOC entry 412 (class 1259 OID 22165)
-- Name: creadores_reporte_integral; Type: TABLE; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE TABLE test.creadores_reporte_integral (
    id_reporte integer NOT NULL,
    creador_tiktok_id character varying(255) NOT NULL,
    creador_id integer,
    usuario_tiktok character varying(100),
    grupo character varying(150),
    agente character varying(200),
    periodo_inicio date NOT NULL,
    periodo_fin date NOT NULL,
    fecha_carga timestamp without time zone DEFAULT now(),
    hora_incorporacion timestamp without time zone,
    dias_desde_incorporacion integer,
    estado_graduacion character varying(150),
    diamantes_totales integer,
    duracion_live_minutos integer,
    dias_validos_emisiones_live integer,
    nuevos_seguidores integer,
    emisiones_live integer,
    diamantes_mes integer,
    duracion_live_mes_minutos integer,
    dias_validos_live_mes integer,
    nuevos_seguidores_mes integer,
    emisiones_live_mes integer,
    porcentaje_logro_diamantes numeric(8,2),
    porcentaje_logro_duracion_live numeric(8,2),
    porcentaje_logro_dias_validos numeric(8,2),
    porcentaje_logro_nuevos_seguidores numeric(8,2),
    porcentaje_logro_emisiones numeric(8,2),
    variacion_diamantes_mes_anterior numeric(8,2),
    variacion_duracion_live_mes_anterior numeric(8,2),
    variacion_dias_validos_mes_anterior numeric(8,2),
    variacion_nuevos_seguidores_mes_anterior numeric(8,2),
    variacion_emisiones_mes_anterior numeric(8,2),
    partidas integer,
    diamantes_de_partidas integer,
    nuevos_creadores_live character varying(20),
    diamantes_modo_varios_invitados integer,
    diamantes_modo_varios_invitados_anfitrion integer,
    diamantes_modo_varios_invitados_invitado integer,
    base_diamantes_antes_unirse integer,
    importacion_id integer,
    tipo_periodo character varying(20) DEFAULT 'semanal'::character varying,
    archivo_origen character varying(255),
    estado_rango character varying(150),
    manager_id integer,
    estado_agencia character varying(50) DEFAULT 'activo'::character varying,
    CONSTRAINT chk_creadores_reporte_integral_tipo_periodo CHECK (((tipo_periodo)::text = ANY ((ARRAY['semanal'::character varying, 'mensual'::character varying, 'otro'::character varying])::text[])))
);


ALTER TABLE test.creadores_reporte_integral OWNER TO whatsapp_db_vsfq_user;

--
-- TOC entry 411 (class 1259 OID 22164)
-- Name: creadores_reporte_integral_id_reporte_seq; Type: SEQUENCE; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE SEQUENCE test.creadores_reporte_integral_id_reporte_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE test.creadores_reporte_integral_id_reporte_seq OWNER TO whatsapp_db_vsfq_user;

--
-- TOC entry 4524 (class 0 OID 0)
-- Dependencies: 411
-- Name: creadores_reporte_integral_id_reporte_seq; Type: SEQUENCE OWNED BY; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER SEQUENCE test.creadores_reporte_integral_id_reporte_seq OWNED BY test.creadores_reporte_integral.id_reporte;


--
-- TOC entry 329 (class 1259 OID 20941)
-- Name: diagnostico_categoria; Type: TABLE; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE TABLE test.diagnostico_categoria (
    id integer NOT NULL,
    nombre character varying(100) NOT NULL,
    descripcion character varying(300),
    activo boolean DEFAULT true,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    nombre_natural character varying(100)
);


ALTER TABLE test.diagnostico_categoria OWNER TO whatsapp_db_vsfq_user;

--
-- TOC entry 328 (class 1259 OID 20940)
-- Name: diagnostico_categoria_id_seq; Type: SEQUENCE; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE SEQUENCE test.diagnostico_categoria_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE test.diagnostico_categoria_id_seq OWNER TO whatsapp_db_vsfq_user;

--
-- TOC entry 4525 (class 0 OID 0)
-- Dependencies: 328
-- Name: diagnostico_categoria_id_seq; Type: SEQUENCE OWNED BY; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER SEQUENCE test.diagnostico_categoria_id_seq OWNED BY test.diagnostico_categoria.id;


--
-- TOC entry 312 (class 1259 OID 20668)
-- Name: diagnostico_interpretacion_categoria; Type: TABLE; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE TABLE test.diagnostico_interpretacion_categoria (
    id integer NOT NULL,
    categoria_id integer NOT NULL,
    escala integer NOT NULL,
    nivel integer NOT NULL,
    script character varying(300) NOT NULL,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


ALTER TABLE test.diagnostico_interpretacion_categoria OWNER TO whatsapp_db_vsfq_user;

--
-- TOC entry 364 (class 1259 OID 21392)
-- Name: diagnostico_mejoras_sugeridas; Type: TABLE; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE TABLE test.diagnostico_mejoras_sugeridas (
    id integer NOT NULL,
    categoria_id integer NOT NULL,
    nivel_min integer,
    nivel_max integer,
    prioridad integer DEFAULT 1,
    texto text NOT NULL,
    tipo character varying(20) DEFAULT 'principal'::character varying,
    activo boolean DEFAULT true,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


ALTER TABLE test.diagnostico_mejoras_sugeridas OWNER TO whatsapp_db_vsfq_user;

--
-- TOC entry 363 (class 1259 OID 21391)
-- Name: diagnostico_mejoras_sugeridas_id_seq; Type: SEQUENCE; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE SEQUENCE test.diagnostico_mejoras_sugeridas_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE test.diagnostico_mejoras_sugeridas_id_seq OWNER TO whatsapp_db_vsfq_user;

--
-- TOC entry 4526 (class 0 OID 0)
-- Dependencies: 363
-- Name: diagnostico_mejoras_sugeridas_id_seq; Type: SEQUENCE OWNED BY; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER SEQUENCE test.diagnostico_mejoras_sugeridas_id_seq OWNED BY test.diagnostico_mejoras_sugeridas.id;


--
-- TOC entry 368 (class 1259 OID 21419)
-- Name: diagnostico_mejoras_variable; Type: TABLE; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE TABLE test.diagnostico_mejoras_variable (
    id integer NOT NULL,
    variable_id integer NOT NULL,
    score_max numeric(4,2) DEFAULT 2 NOT NULL,
    prioridad integer DEFAULT 1 NOT NULL,
    texto text NOT NULL,
    activo boolean DEFAULT true NOT NULL,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


ALTER TABLE test.diagnostico_mejoras_variable OWNER TO whatsapp_db_vsfq_user;

--
-- TOC entry 367 (class 1259 OID 21418)
-- Name: diagnostico_mejoras_variable_id_seq; Type: SEQUENCE; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE SEQUENCE test.diagnostico_mejoras_variable_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE test.diagnostico_mejoras_variable_id_seq OWNER TO whatsapp_db_vsfq_user;

--
-- TOC entry 4527 (class 0 OID 0)
-- Dependencies: 367
-- Name: diagnostico_mejoras_variable_id_seq; Type: SEQUENCE OWNED BY; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER SEQUENCE test.diagnostico_mejoras_variable_id_seq OWNED BY test.diagnostico_mejoras_variable.id;


--
-- TOC entry 298 (class 1259 OID 20273)
-- Name: diagnostico_modelo; Type: TABLE; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE TABLE test.diagnostico_modelo (
    id integer NOT NULL,
    nombre character varying(100) NOT NULL,
    descripcion text,
    activo boolean DEFAULT true,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


ALTER TABLE test.diagnostico_modelo OWNER TO whatsapp_db_vsfq_user;

--
-- TOC entry 331 (class 1259 OID 20962)
-- Name: diagnostico_modelo_categoria; Type: TABLE; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE TABLE test.diagnostico_modelo_categoria (
    id integer NOT NULL,
    modelo_id integer NOT NULL,
    categoria_id integer NOT NULL,
    peso_categoria numeric(5,2) NOT NULL,
    orden integer,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


ALTER TABLE test.diagnostico_modelo_categoria OWNER TO whatsapp_db_vsfq_user;

--
-- TOC entry 330 (class 1259 OID 20961)
-- Name: diagnostico_modelo_categoria_id_seq; Type: SEQUENCE; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE SEQUENCE test.diagnostico_modelo_categoria_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE test.diagnostico_modelo_categoria_id_seq OWNER TO whatsapp_db_vsfq_user;

--
-- TOC entry 4528 (class 0 OID 0)
-- Dependencies: 330
-- Name: diagnostico_modelo_categoria_id_seq; Type: SEQUENCE OWNED BY; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER SEQUENCE test.diagnostico_modelo_categoria_id_seq OWNED BY test.diagnostico_modelo_categoria.id;


--
-- TOC entry 306 (class 1259 OID 20639)
-- Name: diagnostico_score_categoria; Type: TABLE; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE TABLE test.diagnostico_score_categoria (
    id integer NOT NULL,
    modelo_id integer NOT NULL,
    aspirante_id integer NOT NULL,
    categoria_id integer NOT NULL,
    score_categoria numeric(3,2),
    nivel integer NOT NULL,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


ALTER TABLE test.diagnostico_score_categoria OWNER TO whatsapp_db_vsfq_user;

--
-- TOC entry 310 (class 1259 OID 20657)
-- Name: diagnostico_score_general; Type: TABLE; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE TABLE test.diagnostico_score_general (
    id integer NOT NULL,
    aspirante_id integer,
    modelo_id integer,
    puntaje_total numeric(6,2),
    nivel integer NOT NULL,
    diagnostico_json jsonb,
    diagnostico_resumen character varying(500),
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    texto_whatsapp text
);


ALTER TABLE test.diagnostico_score_general OWNER TO whatsapp_db_vsfq_user;

--
-- TOC entry 327 (class 1259 OID 20926)
-- Name: diagnostico_score_variable; Type: TABLE; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE TABLE test.diagnostico_score_variable (
    id integer NOT NULL,
    aspirante_id integer NOT NULL,
    variable_id integer NOT NULL,
    valor integer,
    valor_id integer,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


ALTER TABLE test.diagnostico_score_variable OWNER TO whatsapp_db_vsfq_user;

--
-- TOC entry 326 (class 1259 OID 20925)
-- Name: diagnostico_score_variable_id_seq; Type: SEQUENCE; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE SEQUENCE test.diagnostico_score_variable_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE test.diagnostico_score_variable_id_seq OWNER TO whatsapp_db_vsfq_user;

--
-- TOC entry 4529 (class 0 OID 0)
-- Dependencies: 326
-- Name: diagnostico_score_variable_id_seq; Type: SEQUENCE OWNED BY; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER SEQUENCE test.diagnostico_score_variable_id_seq OWNED BY test.diagnostico_score_variable.id;


--
-- TOC entry 323 (class 1259 OID 20810)
-- Name: diagnostico_variable; Type: TABLE; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE TABLE test.diagnostico_variable (
    id integer NOT NULL,
    categoria_id integer,
    nombre character varying(100),
    campo_db character varying(100),
    peso_variable numeric(5,2),
    tipo character varying(50),
    created_at timestamp without time zone,
    encuesta_id integer,
    activa boolean DEFAULT true,
    tipo_form character varying(15),
    texto character varying(300),
    orden integer,
    migrado boolean DEFAULT false
);


ALTER TABLE test.diagnostico_variable OWNER TO whatsapp_db_vsfq_user;

--
-- TOC entry 322 (class 1259 OID 20809)
-- Name: diagnostico_variable_new_id_seq; Type: SEQUENCE; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE SEQUENCE test.diagnostico_variable_new_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE test.diagnostico_variable_new_id_seq OWNER TO whatsapp_db_vsfq_user;

--
-- TOC entry 4530 (class 0 OID 0)
-- Dependencies: 322
-- Name: diagnostico_variable_new_id_seq; Type: SEQUENCE OWNED BY; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER SEQUENCE test.diagnostico_variable_new_id_seq OWNED BY test.diagnostico_variable.id;


--
-- TOC entry 321 (class 1259 OID 20779)
-- Name: diagnostico_variable_valor; Type: TABLE; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE TABLE test.diagnostico_variable_valor (
    id integer DEFAULT nextval('test.modelo_variable_valor_id_seq'::regclass) NOT NULL,
    variable_id integer NOT NULL,
    min_val numeric,
    max_val numeric,
    score integer NOT NULL,
    label character varying(80) NOT NULL,
    nivel character varying(20),
    orden integer,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


ALTER TABLE test.diagnostico_variable_valor OWNER TO whatsapp_db_vsfq_user;

--
-- TOC entry 302 (class 1259 OID 20409)
-- Name: encuestas; Type: TABLE; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE TABLE test.encuestas (
    id integer NOT NULL,
    nombre character varying(100) NOT NULL,
    descripcion text,
    activa boolean DEFAULT true
);


ALTER TABLE test.encuestas OWNER TO whatsapp_db_vsfq_user;

--
-- TOC entry 335 (class 1259 OID 21005)
-- Name: entrevista_tipo; Type: TABLE; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE TABLE test.entrevista_tipo (
    id integer NOT NULL,
    nombre character varying(100) NOT NULL,
    descripcion character varying(200),
    duracion_default integer,
    tipo character varying(30),
    activo boolean DEFAULT true,
    orden integer DEFAULT 1,
    created_at timestamp without time zone DEFAULT now()
);


ALTER TABLE test.entrevista_tipo OWNER TO whatsapp_db_vsfq_user;

--
-- TOC entry 334 (class 1259 OID 21004)
-- Name: entrevista_tipo_id_seq; Type: SEQUENCE; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE SEQUENCE test.entrevista_tipo_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE test.entrevista_tipo_id_seq OWNER TO whatsapp_db_vsfq_user;

--
-- TOC entry 4531 (class 0 OID 0)
-- Dependencies: 334
-- Name: entrevista_tipo_id_seq; Type: SEQUENCE OWNED BY; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER SEQUENCE test.entrevista_tipo_id_seq OWNED BY test.entrevista_tipo.id;


--
-- TOC entry 337 (class 1259 OID 21043)
-- Name: entrevistas; Type: TABLE; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE TABLE test.entrevistas (
    id integer NOT NULL,
    aspirante_id integer NOT NULL,
    agendamiento_id integer,
    entrevista_tipo_id integer,
    usuario_evalua integer,
    observaciones character varying(500),
    aspecto_tecnico smallint,
    presencia_carisma smallint,
    interaccion_audiencia smallint,
    profesionalismo_normas smallint,
    score_total_entrevista numeric(3,2),
    score_total numeric(3,2),
    estado_id smallint,
    creado_en timestamp without time zone DEFAULT now(),
    actualizado_en timestamp without time zone DEFAULT now(),
    decision_final character varying(30),
    observacion_decision character varying(300)
);


ALTER TABLE test.entrevistas OWNER TO whatsapp_db_vsfq_user;

--
-- TOC entry 336 (class 1259 OID 21042)
-- Name: entrevistas_id_seq; Type: SEQUENCE; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE SEQUENCE test.entrevistas_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE test.entrevistas_id_seq OWNER TO whatsapp_db_vsfq_user;

--
-- TOC entry 4532 (class 0 OID 0)
-- Dependencies: 336
-- Name: entrevistas_id_seq; Type: SEQUENCE OWNED BY; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER SEQUENCE test.entrevistas_id_seq OWNED BY test.entrevistas.id;


--
-- TOC entry 374 (class 1259 OID 21490)
-- Name: entrevistas_interpretacion_variable; Type: TABLE; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE TABLE test.entrevistas_interpretacion_variable (
    id integer NOT NULL,
    entrevista_tipo_id integer,
    variable_codigo character varying(50) NOT NULL,
    nivel smallint NOT NULL,
    etiqueta character varying(100),
    categoria_resultado character varying(20),
    mensaje_corto character varying(250),
    mensaje_largo text,
    recomendacion text,
    activo boolean DEFAULT true,
    creado_en timestamp without time zone DEFAULT now(),
    actualizado_en timestamp without time zone DEFAULT now(),
    CONSTRAINT entrevistas_interpretacion_variable_nivel_check CHECK (((nivel >= 1) AND (nivel <= 5)))
);


ALTER TABLE test.entrevistas_interpretacion_variable OWNER TO whatsapp_db_vsfq_user;

--
-- TOC entry 373 (class 1259 OID 21489)
-- Name: entrevistas_interpretacion_variable_id_seq; Type: SEQUENCE; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE SEQUENCE test.entrevistas_interpretacion_variable_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE test.entrevistas_interpretacion_variable_id_seq OWNER TO whatsapp_db_vsfq_user;

--
-- TOC entry 4533 (class 0 OID 0)
-- Dependencies: 373
-- Name: entrevistas_interpretacion_variable_id_seq; Type: SEQUENCE OWNED BY; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER SEQUENCE test.entrevistas_interpretacion_variable_id_seq OWNED BY test.entrevistas_interpretacion_variable.id;


--
-- TOC entry 370 (class 1259 OID 21455)
-- Name: entrevistas_variable; Type: TABLE; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE TABLE test.entrevistas_variable (
    codigo character varying(50) NOT NULL,
    nombre character varying(100) NOT NULL,
    descripcion character varying(250),
    activo boolean DEFAULT true
);


ALTER TABLE test.entrevistas_variable OWNER TO whatsapp_db_vsfq_user;

--
-- TOC entry 301 (class 1259 OID 20408)
-- Name: form_encuestas_id_seq; Type: SEQUENCE; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE SEQUENCE test.form_encuestas_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE test.form_encuestas_id_seq OWNER TO whatsapp_db_vsfq_user;

--
-- TOC entry 4534 (class 0 OID 0)
-- Dependencies: 301
-- Name: form_encuestas_id_seq; Type: SEQUENCE OWNED BY; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER SEQUENCE test.form_encuestas_id_seq OWNED BY test.encuestas.id;


--
-- TOC entry 441 (class 1259 OID 22450)
-- Name: ia_base_conocimiento; Type: TABLE; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE TABLE test.ia_base_conocimiento (
    id integer NOT NULL,
    modulo character varying(80) NOT NULL,
    categoria character varying(80) NOT NULL,
    subcategoria character varying(120),
    titulo character varying(200) NOT NULL,
    resumen text NOT NULL,
    accion_recomendada text,
    ejemplo_manager text,
    aplica_cuando text,
    fuente character varying(200),
    prioridad integer DEFAULT 1,
    activo boolean DEFAULT true,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


ALTER TABLE test.ia_base_conocimiento OWNER TO whatsapp_db_vsfq_user;

--
-- TOC entry 440 (class 1259 OID 22449)
-- Name: ia_base_conocimiento_id_seq; Type: SEQUENCE; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE SEQUENCE test.ia_base_conocimiento_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE test.ia_base_conocimiento_id_seq OWNER TO whatsapp_db_vsfq_user;

--
-- TOC entry 4535 (class 0 OID 0)
-- Dependencies: 440
-- Name: ia_base_conocimiento_id_seq; Type: SEQUENCE OWNED BY; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER SEQUENCE test.ia_base_conocimiento_id_seq OWNED BY test.ia_base_conocimiento.id;


--
-- TOC entry 341 (class 1259 OID 21071)
-- Name: invitaciones; Type: TABLE; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE TABLE test.invitaciones (
    id integer NOT NULL,
    aspirante_id integer NOT NULL,
    fecha_invitacion date,
    usuario_invita integer,
    manager_id integer,
    estado_invitacion character varying(30) DEFAULT 'pendiente_envio'::character varying NOT NULL,
    estado_tiktok character varying(30) DEFAULT 'pendiente'::character varying NOT NULL,
    fecha_respuesta_invitacion date,
    fecha_respuesta_tiktok date,
    fecha_incorporacion date,
    mensaje_enviado boolean DEFAULT false NOT NULL,
    solicitud_tiktok_enviada boolean DEFAULT false NOT NULL,
    observaciones character varying(300),
    creado_en timestamp without time zone DEFAULT now(),
    actualizado_en timestamp without time zone DEFAULT now(),
    mensaje_incorporacion_enviado boolean DEFAULT false NOT NULL,
    fecha_mensaje_incorporacion timestamp without time zone
);


ALTER TABLE test.invitaciones OWNER TO whatsapp_db_vsfq_user;

--
-- TOC entry 340 (class 1259 OID 21070)
-- Name: invitaciones_id_seq; Type: SEQUENCE; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE SEQUENCE test.invitaciones_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE test.invitaciones_id_seq OWNER TO whatsapp_db_vsfq_user;

--
-- TOC entry 4536 (class 0 OID 0)
-- Dependencies: 340
-- Name: invitaciones_id_seq; Type: SEQUENCE OWNED BY; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER SEQUENCE test.invitaciones_id_seq OWNED BY test.invitaciones.id;


--
-- TOC entry 271 (class 1259 OID 19486)
-- Name: managers; Type: TABLE; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE TABLE test.managers (
    id integer DEFAULT nextval('public.manager_id_seq'::regclass) NOT NULL,
    nombre character varying(100),
    email character varying(100),
    telefono character varying(20),
    total_diamantes_creadores integer,
    total_creadores integer,
    creado_en timestamp without time zone DEFAULT now()
);


ALTER TABLE test.managers OWNER TO whatsapp_db_vsfq_user;

--
-- TOC entry 288 (class 1259 OID 20098)
-- Name: mensajes_whatsapp; Type: TABLE; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE TABLE test.mensajes_whatsapp (
    id integer NOT NULL,
    usuario_id integer,
    telefono character varying(20) NOT NULL,
    direccion character varying(10) NOT NULL,
    tipo character varying(10) NOT NULL,
    contenido text,
    media_url text,
    message_id_meta character varying(100),
    estado character varying(20) DEFAULT 'sent'::character varying,
    fecha timestamp with time zone DEFAULT now(),
    error_codigo character varying(20),
    error_mensaje character varying(100),
    reenvio_pendiente boolean DEFAULT false,
    recuperado boolean DEFAULT false
);


ALTER TABLE test.mensajes_whatsapp OWNER TO whatsapp_db_vsfq_user;

--
-- TOC entry 388 (class 1259 OID 21603)
-- Name: mensajes_whatsapp_chat_estado; Type: TABLE; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE TABLE test.mensajes_whatsapp_chat_estado (
    telefono character varying(20) NOT NULL,
    last_read_at timestamp without time zone,
    creado_en timestamp without time zone DEFAULT now(),
    actualizado_en timestamp without time zone DEFAULT now()
);


ALTER TABLE test.mensajes_whatsapp_chat_estado OWNER TO whatsapp_db_vsfq_user;

--
-- TOC entry 287 (class 1259 OID 20097)
-- Name: mensajes_whatsapp_id_seq; Type: SEQUENCE; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE SEQUENCE test.mensajes_whatsapp_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE test.mensajes_whatsapp_id_seq OWNER TO whatsapp_db_vsfq_user;

--
-- TOC entry 4537 (class 0 OID 0)
-- Dependencies: 287
-- Name: mensajes_whatsapp_id_seq; Type: SEQUENCE OWNED BY; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER SEQUENCE test.mensajes_whatsapp_id_seq OWNED BY test.mensajes_whatsapp.id;


--
-- TOC entry 297 (class 1259 OID 20272)
-- Name: modelo_evaluacion_id_seq; Type: SEQUENCE; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE SEQUENCE test.modelo_evaluacion_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE test.modelo_evaluacion_id_seq OWNER TO whatsapp_db_vsfq_user;

--
-- TOC entry 4538 (class 0 OID 0)
-- Dependencies: 297
-- Name: modelo_evaluacion_id_seq; Type: SEQUENCE OWNED BY; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER SEQUENCE test.modelo_evaluacion_id_seq OWNED BY test.diagnostico_modelo.id;


--
-- TOC entry 355 (class 1259 OID 21230)
-- Name: participante_tipo; Type: TABLE; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE TABLE test.participante_tipo (
    id integer NOT NULL,
    codigo character varying(20) NOT NULL,
    nombre character varying(50) NOT NULL
);


ALTER TABLE test.participante_tipo OWNER TO whatsapp_db_vsfq_user;

--
-- TOC entry 354 (class 1259 OID 21229)
-- Name: participante_tipo_id_seq; Type: SEQUENCE; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE SEQUENCE test.participante_tipo_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE test.participante_tipo_id_seq OWNER TO whatsapp_db_vsfq_user;

--
-- TOC entry 4539 (class 0 OID 0)
-- Dependencies: 354
-- Name: participante_tipo_id_seq; Type: SEQUENCE OWNED BY; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER SEQUENCE test.participante_tipo_id_seq OWNED BY test.participante_tipo.id;


--
-- TOC entry 349 (class 1259 OID 21179)
-- Name: portal_access_tokens; Type: TABLE; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE TABLE test.portal_access_tokens (
    id bigint NOT NULL,
    token text NOT NULL,
    aspirante_id integer,
    expiracion timestamp without time zone NOT NULL,
    estado character varying(20) DEFAULT 'activo'::character varying NOT NULL,
    creado_en timestamp without time zone DEFAULT now() NOT NULL,
    ultimo_uso_en timestamp without time zone,
    duracion_dias integer DEFAULT 10080 NOT NULL,
    creado_por integer,
    origen character varying(30) DEFAULT 'whatsapp'::character varying,
    creador_id integer,
    tipo_portal character varying(30) DEFAULT 'aspirante'::character varying,
    CONSTRAINT chk_portal_access_tokens_persona CHECK (((aspirante_id IS NOT NULL) OR (creador_id IS NOT NULL))),
    CONSTRAINT chk_portal_access_tokens_tipo_portal CHECK (((tipo_portal)::text = ANY ((ARRAY['aspirante'::character varying, 'creador'::character varying])::text[])))
);


ALTER TABLE test.portal_access_tokens OWNER TO whatsapp_db_vsfq_user;

--
-- TOC entry 348 (class 1259 OID 21178)
-- Name: portal_access_tokens_id_seq; Type: SEQUENCE; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE SEQUENCE test.portal_access_tokens_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE test.portal_access_tokens_id_seq OWNER TO whatsapp_db_vsfq_user;

--
-- TOC entry 4540 (class 0 OID 0)
-- Dependencies: 348
-- Name: portal_access_tokens_id_seq; Type: SEQUENCE OWNED BY; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER SEQUENCE test.portal_access_tokens_id_seq OWNED BY test.portal_access_tokens.id;


--
-- TOC entry 305 (class 1259 OID 20638)
-- Name: talento_score_categoria_id_seq; Type: SEQUENCE; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE SEQUENCE test.talento_score_categoria_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE test.talento_score_categoria_id_seq OWNER TO whatsapp_db_vsfq_user;

--
-- TOC entry 4541 (class 0 OID 0)
-- Dependencies: 305
-- Name: talento_score_categoria_id_seq; Type: SEQUENCE OWNED BY; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER SEQUENCE test.talento_score_categoria_id_seq OWNED BY test.diagnostico_score_categoria.id;


--
-- TOC entry 309 (class 1259 OID 20656)
-- Name: talento_score_general_id_seq; Type: SEQUENCE; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE SEQUENCE test.talento_score_general_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE test.talento_score_general_id_seq OWNER TO whatsapp_db_vsfq_user;

--
-- TOC entry 4542 (class 0 OID 0)
-- Dependencies: 309
-- Name: talento_score_general_id_seq; Type: SEQUENCE OWNED BY; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER SEQUENCE test.talento_score_general_id_seq OWNED BY test.diagnostico_score_general.id;


--
-- TOC entry 311 (class 1259 OID 20667)
-- Name: talento_script_categoria_id_seq; Type: SEQUENCE; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE SEQUENCE test.talento_script_categoria_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE test.talento_script_categoria_id_seq OWNER TO whatsapp_db_vsfq_user;

--
-- TOC entry 4543 (class 0 OID 0)
-- Dependencies: 311
-- Name: talento_script_categoria_id_seq; Type: SEQUENCE OWNED BY; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER SEQUENCE test.talento_script_categoria_id_seq OWNED BY test.diagnostico_interpretacion_categoria.id;


--
-- TOC entry 289 (class 1259 OID 20120)
-- Name: tipos_agendamiento_id_seq; Type: SEQUENCE; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE SEQUENCE test.tipos_agendamiento_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE test.tipos_agendamiento_id_seq OWNER TO whatsapp_db_vsfq_user;

--
-- TOC entry 4544 (class 0 OID 0)
-- Dependencies: 289
-- Name: tipos_agendamiento_id_seq; Type: SEQUENCE OWNED BY; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER SEQUENCE test.tipos_agendamiento_id_seq OWNED BY test.agendamientos_tipo.id;


--
-- TOC entry 427 (class 1259 OID 22326)
-- Name: whatsapp_flujos; Type: TABLE; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE TABLE test.whatsapp_flujos (
    numero character varying(30) NOT NULL,
    paso character varying(50),
    aspirante_id integer,
    payload_json jsonb,
    expiracion timestamp without time zone,
    actualizado_en timestamp without time zone DEFAULT now()
);


ALTER TABLE test.whatsapp_flujos OWNER TO whatsapp_db_vsfq_user;

--
-- TOC entry 280 (class 1259 OID 19685)
-- Name: zona_horaria; Type: TABLE; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE TABLE test.zona_horaria (
    id integer NOT NULL,
    codigo character varying(100) NOT NULL,
    label character varying(200) NOT NULL,
    paises text[] NOT NULL,
    activo boolean DEFAULT true NOT NULL
);


ALTER TABLE test.zona_horaria OWNER TO whatsapp_db_vsfq_user;

--
-- TOC entry 279 (class 1259 OID 19684)
-- Name: zona_horaria_id_seq; Type: SEQUENCE; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE SEQUENCE test.zona_horaria_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE test.zona_horaria_id_seq OWNER TO whatsapp_db_vsfq_user;

--
-- TOC entry 4545 (class 0 OID 0)
-- Dependencies: 279
-- Name: zona_horaria_id_seq; Type: SEQUENCE OWNED BY; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER SEQUENCE test.zona_horaria_id_seq OWNED BY test.zona_horaria.id;


--
-- TOC entry 3865 (class 2604 OID 21166)
-- Name: agendamientos_estados id; Type: DEFAULT; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER TABLE ONLY test.agendamientos_estados ALTER COLUMN id SET DEFAULT nextval('test.agendamientos_estados_id_seq'::regclass);


--
-- TOC entry 3874 (class 2604 OID 21346)
-- Name: agendamientos_medio id; Type: DEFAULT; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER TABLE ONLY test.agendamientos_medio ALTER COLUMN id SET DEFAULT nextval('test.agendamientos_medio_id_seq'::regclass);


--
-- TOC entry 3824 (class 2604 OID 20124)
-- Name: agendamientos_tipo id; Type: DEFAULT; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER TABLE ONLY test.agendamientos_tipo ALTER COLUMN id SET DEFAULT nextval('test.tipos_agendamiento_id_seq'::regclass);


--
-- TOC entry 3896 (class 2604 OID 21527)
-- Name: aspirantes_encuesta_inicial id; Type: DEFAULT; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER TABLE ONLY test.aspirantes_encuesta_inicial ALTER COLUMN id SET DEFAULT nextval('test.aspirantes_encuesta_inicial_id_seq'::regclass);


--
-- TOC entry 3893 (class 2604 OID 21509)
-- Name: aspirantes_estado_historial id; Type: DEFAULT; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER TABLE ONLY test.aspirantes_estado_historial ALTER COLUMN id SET DEFAULT nextval('test.aspirantes_estado_historial_id_seq'::regclass);


--
-- TOC entry 3926 (class 2604 OID 22036)
-- Name: creadores id; Type: DEFAULT; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER TABLE ONLY test.creadores ALTER COLUMN id SET DEFAULT nextval('test.creadores_id_seq'::regclass);


--
-- TOC entry 3971 (class 2604 OID 22424)
-- Name: creadores_arquetipo id; Type: DEFAULT; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER TABLE ONLY test.creadores_arquetipo ALTER COLUMN id SET DEFAULT nextval('test.creadores_arquetipo_id_seq'::regclass);


--
-- TOC entry 4020 (class 2604 OID 22772)
-- Name: creadores_capacitaciones id_capacitacion; Type: DEFAULT; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER TABLE ONLY test.creadores_capacitaciones ALTER COLUMN id_capacitacion SET DEFAULT nextval('test.creadores_capacitaciones_id_capacitacion_seq'::regclass);


--
-- TOC entry 4026 (class 2604 OID 22788)
-- Name: creadores_capacitaciones_seguimiento id_seguimiento; Type: DEFAULT; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER TABLE ONLY test.creadores_capacitaciones_seguimiento ALTER COLUMN id_seguimiento SET DEFAULT nextval('test.creadores_capacitaciones_seguimiento_id_seguimiento_seq'::regclass);


--
-- TOC entry 3951 (class 2604 OID 22314)
-- Name: creadores_categoria id; Type: DEFAULT; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER TABLE ONLY test.creadores_categoria ALTER COLUMN id SET DEFAULT nextval('test.creadores_categoria_id_seq'::regclass);


--
-- TOC entry 3929 (class 2604 OID 22051)
-- Name: creadores_detalle id; Type: DEFAULT; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER TABLE ONLY test.creadores_detalle ALTER COLUMN id SET DEFAULT nextval('test.creadores_detalle_id_seq'::regclass);


--
-- TOC entry 3903 (class 2604 OID 21584)
-- Name: creadores_encuesta_inicial id; Type: DEFAULT; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER TABLE ONLY test.creadores_encuesta_inicial ALTER COLUMN id SET DEFAULT nextval('test.creadores_encuesta_inicial_id_seq'::regclass);


--
-- TOC entry 3943 (class 2604 OID 22193)
-- Name: creadores_insights_mensuales id; Type: DEFAULT; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER TABLE ONLY test.creadores_insights_mensuales ALTER COLUMN id SET DEFAULT nextval('test.creadores_insights_mensuales_id_seq'::regclass);


--
-- TOC entry 3945 (class 2604 OID 22223)
-- Name: creadores_metas_mensuales id; Type: DEFAULT; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER TABLE ONLY test.creadores_metas_mensuales ALTER COLUMN id SET DEFAULT nextval('test.creadores_metas_mensuales_id_seq'::regclass);


--
-- TOC entry 3912 (class 2604 OID 21819)
-- Name: creadores_perfil_categoria id; Type: DEFAULT; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER TABLE ONLY test.creadores_perfil_categoria ALTER COLUMN id SET DEFAULT nextval('test.creadores_perfil_categoria_id_seq'::regclass);


--
-- TOC entry 3923 (class 2604 OID 21850)
-- Name: creadores_perfil_respuesta id; Type: DEFAULT; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER TABLE ONLY test.creadores_perfil_respuesta ALTER COLUMN id SET DEFAULT nextval('test.creadores_perfil_respuesta_id_seq'::regclass);


--
-- TOC entry 3916 (class 2604 OID 21830)
-- Name: creadores_perfil_variable id; Type: DEFAULT; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER TABLE ONLY test.creadores_perfil_variable ALTER COLUMN id SET DEFAULT nextval('test.creadores_perfil_variable_id_seq'::regclass);


--
-- TOC entry 3955 (class 2604 OID 22341)
-- Name: creadores_performance_acciones id; Type: DEFAULT; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER TABLE ONLY test.creadores_performance_acciones ALTER COLUMN id SET DEFAULT nextval('test.creadores_performance_acciones_id_seq'::regclass);


--
-- TOC entry 3960 (class 2604 OID 22359)
-- Name: creadores_performance_alertas id; Type: DEFAULT; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER TABLE ONLY test.creadores_performance_alertas ALTER COLUMN id SET DEFAULT nextval('test.creadores_performance_alertas_id_seq'::regclass);


--
-- TOC entry 3995 (class 2604 OID 22649)
-- Name: creadores_performance_objetivos id_objetivo; Type: DEFAULT; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER TABLE ONLY test.creadores_performance_objetivos ALTER COLUMN id_objetivo SET DEFAULT nextval('test.creadores_performance_objetivos_id_objetivo_seq'::regclass);


--
-- TOC entry 4016 (class 2604 OID 22738)
-- Name: creadores_performance_observaciones id_observacion; Type: DEFAULT; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER TABLE ONLY test.creadores_performance_observaciones ALTER COLUMN id_observacion SET DEFAULT nextval('test.creadores_performance_observaciones_id_observacion_seq'::regclass);


--
-- TOC entry 3985 (class 2604 OID 22617)
-- Name: creadores_performance_rangos_diamantes id_rango; Type: DEFAULT; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER TABLE ONLY test.creadores_performance_rangos_diamantes ALTER COLUMN id_rango SET DEFAULT nextval('test.creadores_performance_rangos_diamantes_id_rango_seq'::regclass);


--
-- TOC entry 3964 (class 2604 OID 22371)
-- Name: creadores_performance_recomendaciones id; Type: DEFAULT; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER TABLE ONLY test.creadores_performance_recomendaciones ALTER COLUMN id SET DEFAULT nextval('test.creadores_performance_recomendaciones_id_seq'::regclass);


--
-- TOC entry 3990 (class 2604 OID 22633)
-- Name: creadores_performance_reglas_estado id_regla; Type: DEFAULT; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER TABLE ONLY test.creadores_performance_reglas_estado ALTER COLUMN id_regla SET DEFAULT nextval('test.creadores_performance_reglas_estado_id_regla_seq'::regclass);


--
-- TOC entry 3969 (class 2604 OID 22392)
-- Name: creadores_performance_resumen id; Type: DEFAULT; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER TABLE ONLY test.creadores_performance_resumen ALTER COLUMN id SET DEFAULT nextval('test.creadores_performance_resumen_id_seq'::regclass);


--
-- TOC entry 3967 (class 2604 OID 22382)
-- Name: creadores_performance_score id; Type: DEFAULT; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER TABLE ONLY test.creadores_performance_score ALTER COLUMN id SET DEFAULT nextval('test.creadores_performance_score_id_seq'::regclass);


--
-- TOC entry 3999 (class 2604 OID 22673)
-- Name: creadores_performance_tablero_cortes id_corte; Type: DEFAULT; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER TABLE ONLY test.creadores_performance_tablero_cortes ALTER COLUMN id_corte SET DEFAULT nextval('test.creadores_performance_tablero_cortes_id_corte_seq'::regclass);


--
-- TOC entry 4003 (class 2604 OID 22689)
-- Name: creadores_performance_tablero_creadores id_tablero_creador; Type: DEFAULT; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER TABLE ONLY test.creadores_performance_tablero_creadores ALTER COLUMN id_tablero_creador SET DEFAULT nextval('test.creadores_performance_tablero_creadores_id_tablero_creador_seq'::regclass);


--
-- TOC entry 4009 (class 2604 OID 22714)
-- Name: creadores_performance_tablero_semanas id_tablero_semana; Type: DEFAULT; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER TABLE ONLY test.creadores_performance_tablero_semanas ALTER COLUMN id_tablero_semana SET DEFAULT nextval('test.creadores_performance_tablero_semanas_id_tablero_semana_seq'::regclass);


--
-- TOC entry 3980 (class 2604 OID 22595)
-- Name: creadores_reporte_importaciones id_importacion; Type: DEFAULT; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER TABLE ONLY test.creadores_reporte_importaciones ALTER COLUMN id_importacion SET DEFAULT nextval('test.creadores_reporte_importaciones_id_importacion_seq'::regclass);


--
-- TOC entry 3939 (class 2604 OID 22168)
-- Name: creadores_reporte_integral id_reporte; Type: DEFAULT; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER TABLE ONLY test.creadores_reporte_integral ALTER COLUMN id_reporte SET DEFAULT nextval('test.creadores_reporte_integral_id_reporte_seq'::regclass);


--
-- TOC entry 3845 (class 2604 OID 20944)
-- Name: diagnostico_categoria id; Type: DEFAULT; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER TABLE ONLY test.diagnostico_categoria ALTER COLUMN id SET DEFAULT nextval('test.diagnostico_categoria_id_seq'::regclass);


--
-- TOC entry 3836 (class 2604 OID 20671)
-- Name: diagnostico_interpretacion_categoria id; Type: DEFAULT; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER TABLE ONLY test.diagnostico_interpretacion_categoria ALTER COLUMN id SET DEFAULT nextval('test.talento_script_categoria_id_seq'::regclass);


--
-- TOC entry 3878 (class 2604 OID 21395)
-- Name: diagnostico_mejoras_sugeridas id; Type: DEFAULT; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER TABLE ONLY test.diagnostico_mejoras_sugeridas ALTER COLUMN id SET DEFAULT nextval('test.diagnostico_mejoras_sugeridas_id_seq'::regclass);


--
-- TOC entry 3883 (class 2604 OID 21422)
-- Name: diagnostico_mejoras_variable id; Type: DEFAULT; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER TABLE ONLY test.diagnostico_mejoras_variable ALTER COLUMN id SET DEFAULT nextval('test.diagnostico_mejoras_variable_id_seq'::regclass);


--
-- TOC entry 3827 (class 2604 OID 20276)
-- Name: diagnostico_modelo id; Type: DEFAULT; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER TABLE ONLY test.diagnostico_modelo ALTER COLUMN id SET DEFAULT nextval('test.modelo_evaluacion_id_seq'::regclass);


--
-- TOC entry 3848 (class 2604 OID 20965)
-- Name: diagnostico_modelo_categoria id; Type: DEFAULT; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER TABLE ONLY test.diagnostico_modelo_categoria ALTER COLUMN id SET DEFAULT nextval('test.diagnostico_modelo_categoria_id_seq'::regclass);


--
-- TOC entry 3832 (class 2604 OID 20642)
-- Name: diagnostico_score_categoria id; Type: DEFAULT; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER TABLE ONLY test.diagnostico_score_categoria ALTER COLUMN id SET DEFAULT nextval('test.talento_score_categoria_id_seq'::regclass);


--
-- TOC entry 3834 (class 2604 OID 20660)
-- Name: diagnostico_score_general id; Type: DEFAULT; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER TABLE ONLY test.diagnostico_score_general ALTER COLUMN id SET DEFAULT nextval('test.talento_score_general_id_seq'::regclass);


--
-- TOC entry 3843 (class 2604 OID 20929)
-- Name: diagnostico_score_variable id; Type: DEFAULT; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER TABLE ONLY test.diagnostico_score_variable ALTER COLUMN id SET DEFAULT nextval('test.diagnostico_score_variable_id_seq'::regclass);


--
-- TOC entry 3840 (class 2604 OID 20813)
-- Name: diagnostico_variable id; Type: DEFAULT; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER TABLE ONLY test.diagnostico_variable ALTER COLUMN id SET DEFAULT nextval('test.diagnostico_variable_new_id_seq'::regclass);


--
-- TOC entry 3830 (class 2604 OID 20412)
-- Name: encuestas id; Type: DEFAULT; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER TABLE ONLY test.encuestas ALTER COLUMN id SET DEFAULT nextval('test.form_encuestas_id_seq'::regclass);


--
-- TOC entry 3850 (class 2604 OID 21008)
-- Name: entrevista_tipo id; Type: DEFAULT; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER TABLE ONLY test.entrevista_tipo ALTER COLUMN id SET DEFAULT nextval('test.entrevista_tipo_id_seq'::regclass);


--
-- TOC entry 3854 (class 2604 OID 21046)
-- Name: entrevistas id; Type: DEFAULT; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER TABLE ONLY test.entrevistas ALTER COLUMN id SET DEFAULT nextval('test.entrevistas_id_seq'::regclass);


--
-- TOC entry 3889 (class 2604 OID 21493)
-- Name: entrevistas_interpretacion_variable id; Type: DEFAULT; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER TABLE ONLY test.entrevistas_interpretacion_variable ALTER COLUMN id SET DEFAULT nextval('test.entrevistas_interpretacion_variable_id_seq'::regclass);


--
-- TOC entry 3975 (class 2604 OID 22453)
-- Name: ia_base_conocimiento id; Type: DEFAULT; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER TABLE ONLY test.ia_base_conocimiento ALTER COLUMN id SET DEFAULT nextval('test.ia_base_conocimiento_id_seq'::regclass);


--
-- TOC entry 3857 (class 2604 OID 21074)
-- Name: invitaciones id; Type: DEFAULT; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER TABLE ONLY test.invitaciones ALTER COLUMN id SET DEFAULT nextval('test.invitaciones_id_seq'::regclass);


--
-- TOC entry 3819 (class 2604 OID 20101)
-- Name: mensajes_whatsapp id; Type: DEFAULT; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER TABLE ONLY test.mensajes_whatsapp ALTER COLUMN id SET DEFAULT nextval('test.mensajes_whatsapp_id_seq'::regclass);


--
-- TOC entry 3873 (class 2604 OID 21233)
-- Name: participante_tipo id; Type: DEFAULT; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER TABLE ONLY test.participante_tipo ALTER COLUMN id SET DEFAULT nextval('test.participante_tipo_id_seq'::regclass);


--
-- TOC entry 3867 (class 2604 OID 21182)
-- Name: portal_access_tokens id; Type: DEFAULT; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER TABLE ONLY test.portal_access_tokens ALTER COLUMN id SET DEFAULT nextval('test.portal_access_tokens_id_seq'::regclass);


--
-- TOC entry 3812 (class 2604 OID 19688)
-- Name: zona_horaria id; Type: DEFAULT; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER TABLE ONLY test.zona_horaria ALTER COLUMN id SET DEFAULT nextval('test.zona_horaria_id_seq'::regclass);


--
-- TOC entry 4046 (class 2606 OID 19383)
-- Name: administradores admin_usuario_pkey; Type: CONSTRAINT; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER TABLE ONLY test.administradores
    ADD CONSTRAINT admin_usuario_pkey PRIMARY KEY (id);


--
-- TOC entry 4048 (class 2606 OID 19385)
-- Name: administradores admin_usuario_username_key; Type: CONSTRAINT; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER TABLE ONLY test.administradores
    ADD CONSTRAINT admin_usuario_username_key UNIQUE (username);


--
-- TOC entry 4169 (class 2606 OID 21169)
-- Name: agendamientos_estados agendamientos_estados_pkey; Type: CONSTRAINT; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER TABLE ONLY test.agendamientos_estados
    ADD CONSTRAINT agendamientos_estados_pkey PRIMARY KEY (id);


--
-- TOC entry 4181 (class 2606 OID 21353)
-- Name: agendamientos_medio agendamientos_medio_codigo_key; Type: CONSTRAINT; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER TABLE ONLY test.agendamientos_medio
    ADD CONSTRAINT agendamientos_medio_codigo_key UNIQUE (codigo);


--
-- TOC entry 4183 (class 2606 OID 21351)
-- Name: agendamientos_medio agendamientos_medio_pkey; Type: CONSTRAINT; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER TABLE ONLY test.agendamientos_medio
    ADD CONSTRAINT agendamientos_medio_pkey PRIMARY KEY (id);


--
-- TOC entry 4054 (class 2606 OID 19403)
-- Name: agendamientos_participantes agendamientos_participantes_pkey; Type: CONSTRAINT; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER TABLE ONLY test.agendamientos_participantes
    ADD CONSTRAINT agendamientos_participantes_pkey PRIMARY KEY (id);


--
-- TOC entry 4051 (class 2606 OID 19395)
-- Name: agendamientos agendamientos_pkey; Type: CONSTRAINT; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER TABLE ONLY test.agendamientos
    ADD CONSTRAINT agendamientos_pkey PRIMARY KEY (id);


--
-- TOC entry 4195 (class 2606 OID 21513)
-- Name: aspirantes_estado_historial aspirantes_estado_historial_pkey; Type: CONSTRAINT; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER TABLE ONLY test.aspirantes_estado_historial
    ADD CONSTRAINT aspirantes_estado_historial_pkey PRIMARY KEY (id);


--
-- TOC entry 4058 (class 2606 OID 19424)
-- Name: aspirantes_cargue cargue_creadores_pkey; Type: CONSTRAINT; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER TABLE ONLY test.aspirantes_cargue
    ADD CONSTRAINT cargue_creadores_pkey PRIMARY KEY (id);


--
-- TOC entry 4060 (class 2606 OID 19426)
-- Name: aspirantes_cargue cargue_creadores_usuario_hoja_excel_key; Type: CONSTRAINT; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER TABLE ONLY test.aspirantes_cargue
    ADD CONSTRAINT cargue_creadores_usuario_hoja_excel_key UNIQUE (usuario, hoja_excel);


--
-- TOC entry 4095 (class 2606 OID 20082)
-- Name: configuracion_agencia configuracion_agencia_pkey; Type: CONSTRAINT; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER TABLE ONLY test.configuracion_agencia
    ADD CONSTRAINT configuracion_agencia_pkey PRIMARY KEY (clave);


--
-- TOC entry 4213 (class 2606 OID 22043)
-- Name: creadores creador_pkey; Type: CONSTRAINT; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER TABLE ONLY test.creadores
    ADD CONSTRAINT creador_pkey PRIMARY KEY (id);


--
-- TOC entry 4263 (class 2606 OID 22433)
-- Name: creadores_arquetipo creadores_arquetipo_codigo_key; Type: CONSTRAINT; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER TABLE ONLY test.creadores_arquetipo
    ADD CONSTRAINT creadores_arquetipo_codigo_key UNIQUE (codigo);


--
-- TOC entry 4265 (class 2606 OID 22431)
-- Name: creadores_arquetipo creadores_arquetipo_pkey; Type: CONSTRAINT; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER TABLE ONLY test.creadores_arquetipo
    ADD CONSTRAINT creadores_arquetipo_pkey PRIMARY KEY (id);


--
-- TOC entry 4320 (class 2606 OID 22781)
-- Name: creadores_capacitaciones creadores_capacitaciones_pkey; Type: CONSTRAINT; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER TABLE ONLY test.creadores_capacitaciones
    ADD CONSTRAINT creadores_capacitaciones_pkey PRIMARY KEY (id_capacitacion);


--
-- TOC entry 4325 (class 2606 OID 22796)
-- Name: creadores_capacitaciones_seguimiento creadores_capacitaciones_seguimiento_pkey; Type: CONSTRAINT; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER TABLE ONLY test.creadores_capacitaciones_seguimiento
    ADD CONSTRAINT creadores_capacitaciones_seguimiento_pkey PRIMARY KEY (id_seguimiento);


--
-- TOC entry 4243 (class 2606 OID 22320)
-- Name: creadores_categoria creadores_categoria_nombre_key; Type: CONSTRAINT; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER TABLE ONLY test.creadores_categoria
    ADD CONSTRAINT creadores_categoria_nombre_key UNIQUE (nombre);


--
-- TOC entry 4245 (class 2606 OID 22318)
-- Name: creadores_categoria creadores_categoria_pkey; Type: CONSTRAINT; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER TABLE ONLY test.creadores_categoria
    ADD CONSTRAINT creadores_categoria_pkey PRIMARY KEY (id);


--
-- TOC entry 4218 (class 2606 OID 22062)
-- Name: creadores_detalle creadores_detalle_pkey; Type: CONSTRAINT; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER TABLE ONLY test.creadores_detalle
    ADD CONSTRAINT creadores_detalle_pkey PRIMARY KEY (id);


--
-- TOC entry 4239 (class 2606 OID 22292)
-- Name: creadores_estados creadores_estados_nombre_key; Type: CONSTRAINT; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER TABLE ONLY test.creadores_estados
    ADD CONSTRAINT creadores_estados_nombre_key UNIQUE (nombre);


--
-- TOC entry 4241 (class 2606 OID 22290)
-- Name: creadores_estados creadores_estados_pkey; Type: CONSTRAINT; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER TABLE ONLY test.creadores_estados
    ADD CONSTRAINT creadores_estados_pkey PRIMARY KEY (id);


--
-- TOC entry 4233 (class 2606 OID 22198)
-- Name: creadores_insights_mensuales creadores_insights_mensuales_pkey; Type: CONSTRAINT; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER TABLE ONLY test.creadores_insights_mensuales
    ADD CONSTRAINT creadores_insights_mensuales_pkey PRIMARY KEY (id);


--
-- TOC entry 4235 (class 2606 OID 22227)
-- Name: creadores_metas_mensuales creadores_metas_mensuales_pkey; Type: CONSTRAINT; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER TABLE ONLY test.creadores_metas_mensuales
    ADD CONSTRAINT creadores_metas_mensuales_pkey PRIMARY KEY (id);


--
-- TOC entry 4205 (class 2606 OID 21825)
-- Name: creadores_perfil_categoria creadores_perfil_categoria_pkey; Type: CONSTRAINT; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER TABLE ONLY test.creadores_perfil_categoria
    ADD CONSTRAINT creadores_perfil_categoria_pkey PRIMARY KEY (id);


--
-- TOC entry 4209 (class 2606 OID 21856)
-- Name: creadores_perfil_respuesta creadores_perfil_respuesta_pkey; Type: CONSTRAINT; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER TABLE ONLY test.creadores_perfil_respuesta
    ADD CONSTRAINT creadores_perfil_respuesta_pkey PRIMARY KEY (id);


--
-- TOC entry 4207 (class 2606 OID 21838)
-- Name: creadores_perfil_variable creadores_perfil_variable_pkey; Type: CONSTRAINT; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER TABLE ONLY test.creadores_perfil_variable
    ADD CONSTRAINT creadores_perfil_variable_pkey PRIMARY KEY (id);


--
-- TOC entry 4249 (class 2606 OID 22349)
-- Name: creadores_performance_acciones creadores_performance_acciones_pkey; Type: CONSTRAINT; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER TABLE ONLY test.creadores_performance_acciones
    ADD CONSTRAINT creadores_performance_acciones_pkey PRIMARY KEY (id);


--
-- TOC entry 4252 (class 2606 OID 22366)
-- Name: creadores_performance_alertas creadores_performance_alertas_pkey; Type: CONSTRAINT; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER TABLE ONLY test.creadores_performance_alertas
    ADD CONSTRAINT creadores_performance_alertas_pkey PRIMARY KEY (id);


--
-- TOC entry 4284 (class 2606 OID 22658)
-- Name: creadores_performance_objetivos creadores_performance_objetivos_pkey; Type: CONSTRAINT; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER TABLE ONLY test.creadores_performance_objetivos
    ADD CONSTRAINT creadores_performance_objetivos_pkey PRIMARY KEY (id_objetivo);


--
-- TOC entry 4312 (class 2606 OID 22745)
-- Name: creadores_performance_observaciones creadores_performance_observaciones_pkey; Type: CONSTRAINT; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER TABLE ONLY test.creadores_performance_observaciones
    ADD CONSTRAINT creadores_performance_observaciones_pkey PRIMARY KEY (id_observacion);


--
-- TOC entry 4277 (class 2606 OID 22626)
-- Name: creadores_performance_rangos_diamantes creadores_performance_rangos_diamantes_pkey; Type: CONSTRAINT; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER TABLE ONLY test.creadores_performance_rangos_diamantes
    ADD CONSTRAINT creadores_performance_rangos_diamantes_pkey PRIMARY KEY (id_rango);


--
-- TOC entry 4255 (class 2606 OID 22377)
-- Name: creadores_performance_recomendaciones creadores_performance_recomendaciones_pkey; Type: CONSTRAINT; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER TABLE ONLY test.creadores_performance_recomendaciones
    ADD CONSTRAINT creadores_performance_recomendaciones_pkey PRIMARY KEY (id);


--
-- TOC entry 4281 (class 2606 OID 22643)
-- Name: creadores_performance_reglas_estado creadores_performance_reglas_estado_pkey; Type: CONSTRAINT; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER TABLE ONLY test.creadores_performance_reglas_estado
    ADD CONSTRAINT creadores_performance_reglas_estado_pkey PRIMARY KEY (id_regla);


--
-- TOC entry 4260 (class 2606 OID 22395)
-- Name: creadores_performance_resumen creadores_performance_resumen_pkey; Type: CONSTRAINT; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER TABLE ONLY test.creadores_performance_resumen
    ADD CONSTRAINT creadores_performance_resumen_pkey PRIMARY KEY (id);


--
-- TOC entry 4257 (class 2606 OID 22387)
-- Name: creadores_performance_score creadores_performance_score_pkey; Type: CONSTRAINT; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER TABLE ONLY test.creadores_performance_score
    ADD CONSTRAINT creadores_performance_score_pkey PRIMARY KEY (id);


--
-- TOC entry 4291 (class 2606 OID 22682)
-- Name: creadores_performance_tablero_cortes creadores_performance_tablero_cortes_pkey; Type: CONSTRAINT; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER TABLE ONLY test.creadores_performance_tablero_cortes
    ADD CONSTRAINT creadores_performance_tablero_cortes_pkey PRIMARY KEY (id_corte);


--
-- TOC entry 4295 (class 2606 OID 22697)
-- Name: creadores_performance_tablero_creadores creadores_performance_tablero_creadores_pkey; Type: CONSTRAINT; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER TABLE ONLY test.creadores_performance_tablero_creadores
    ADD CONSTRAINT creadores_performance_tablero_creadores_pkey PRIMARY KEY (id_tablero_creador);


--
-- TOC entry 4304 (class 2606 OID 22722)
-- Name: creadores_performance_tablero_semanas creadores_performance_tablero_semanas_pkey; Type: CONSTRAINT; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER TABLE ONLY test.creadores_performance_tablero_semanas
    ADD CONSTRAINT creadores_performance_tablero_semanas_pkey PRIMARY KEY (id_tablero_semana);


--
-- TOC entry 4063 (class 2606 OID 19440)
-- Name: aspirantes creadores_pkey; Type: CONSTRAINT; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER TABLE ONLY test.aspirantes
    ADD CONSTRAINT creadores_pkey PRIMARY KEY (id);


--
-- TOC entry 4275 (class 2606 OID 22605)
-- Name: creadores_reporte_importaciones creadores_reporte_importaciones_pkey; Type: CONSTRAINT; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER TABLE ONLY test.creadores_reporte_importaciones
    ADD CONSTRAINT creadores_reporte_importaciones_pkey PRIMARY KEY (id_importacion);


--
-- TOC entry 4222 (class 2606 OID 22173)
-- Name: creadores_reporte_integral creadores_reporte_integral_pkey; Type: CONSTRAINT; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER TABLE ONLY test.creadores_reporte_integral
    ADD CONSTRAINT creadores_reporte_integral_pkey PRIMARY KEY (id_reporte);


--
-- TOC entry 4065 (class 2606 OID 19442)
-- Name: aspirantes creadores_usuario_key; Type: CONSTRAINT; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER TABLE ONLY test.aspirantes
    ADD CONSTRAINT creadores_usuario_key UNIQUE (usuario);


--
-- TOC entry 4151 (class 2606 OID 20948)
-- Name: diagnostico_categoria diagnostico_categoria_pkey; Type: CONSTRAINT; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER TABLE ONLY test.diagnostico_categoria
    ADD CONSTRAINT diagnostico_categoria_pkey PRIMARY KEY (id);


--
-- TOC entry 4185 (class 2606 OID 21403)
-- Name: diagnostico_mejoras_sugeridas diagnostico_mejoras_sugeridas_pkey; Type: CONSTRAINT; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER TABLE ONLY test.diagnostico_mejoras_sugeridas
    ADD CONSTRAINT diagnostico_mejoras_sugeridas_pkey PRIMARY KEY (id);


--
-- TOC entry 4187 (class 2606 OID 21430)
-- Name: diagnostico_mejoras_variable diagnostico_mejoras_variable_pkey; Type: CONSTRAINT; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER TABLE ONLY test.diagnostico_mejoras_variable
    ADD CONSTRAINT diagnostico_mejoras_variable_pkey PRIMARY KEY (id);


--
-- TOC entry 4155 (class 2606 OID 20968)
-- Name: diagnostico_modelo_categoria diagnostico_modelo_categoria_pkey; Type: CONSTRAINT; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER TABLE ONLY test.diagnostico_modelo_categoria
    ADD CONSTRAINT diagnostico_modelo_categoria_pkey PRIMARY KEY (id);


--
-- TOC entry 4142 (class 2606 OID 20932)
-- Name: diagnostico_score_variable diagnostico_score_variable_pkey; Type: CONSTRAINT; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER TABLE ONLY test.diagnostico_score_variable
    ADD CONSTRAINT diagnostico_score_variable_pkey PRIMARY KEY (id);


--
-- TOC entry 4137 (class 2606 OID 20816)
-- Name: diagnostico_variable diagnostico_variable_new_pkey; Type: CONSTRAINT; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER TABLE ONLY test.diagnostico_variable
    ADD CONSTRAINT diagnostico_variable_new_pkey PRIMARY KEY (id);


--
-- TOC entry 4197 (class 2606 OID 21537)
-- Name: aspirantes_encuesta_inicial encuesta_inicial_registros_pkey; Type: CONSTRAINT; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER TABLE ONLY test.aspirantes_encuesta_inicial
    ADD CONSTRAINT encuesta_inicial_registros_pkey PRIMARY KEY (id);


--
-- TOC entry 4160 (class 2606 OID 21013)
-- Name: entrevista_tipo entrevista_tipo_pkey; Type: CONSTRAINT; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER TABLE ONLY test.entrevista_tipo
    ADD CONSTRAINT entrevista_tipo_pkey PRIMARY KEY (id);


--
-- TOC entry 4191 (class 2606 OID 21501)
-- Name: entrevistas_interpretacion_variable entrevistas_interpretacion_variable_pkey; Type: CONSTRAINT; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER TABLE ONLY test.entrevistas_interpretacion_variable
    ADD CONSTRAINT entrevistas_interpretacion_variable_pkey PRIMARY KEY (id);


--
-- TOC entry 4193 (class 2606 OID 21503)
-- Name: entrevistas_interpretacion_variable entrevistas_interpretacion_variable_unq; Type: CONSTRAINT; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER TABLE ONLY test.entrevistas_interpretacion_variable
    ADD CONSTRAINT entrevistas_interpretacion_variable_unq UNIQUE (entrevista_tipo_id, variable_codigo, nivel);


--
-- TOC entry 4162 (class 2606 OID 21051)
-- Name: entrevistas entrevistas_pkey; Type: CONSTRAINT; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER TABLE ONLY test.entrevistas
    ADD CONSTRAINT entrevistas_pkey PRIMARY KEY (id);


--
-- TOC entry 4189 (class 2606 OID 21460)
-- Name: entrevistas_variable entrevistas_variable_pkey; Type: CONSTRAINT; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER TABLE ONLY test.entrevistas_variable
    ADD CONSTRAINT entrevistas_variable_pkey PRIMARY KEY (codigo);


--
-- TOC entry 4067 (class 2606 OID 19476)
-- Name: aspirantes_estados estados_creador_nombre_key; Type: CONSTRAINT; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER TABLE ONLY test.aspirantes_estados
    ADD CONSTRAINT estados_creador_nombre_key UNIQUE (nombre);


--
-- TOC entry 4069 (class 2606 OID 19474)
-- Name: aspirantes_estados estados_creador_pkey; Type: CONSTRAINT; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER TABLE ONLY test.aspirantes_estados
    ADD CONSTRAINT estados_creador_pkey PRIMARY KEY (id);


--
-- TOC entry 4112 (class 2606 OID 20417)
-- Name: encuestas form_encuestas_pkey; Type: CONSTRAINT; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER TABLE ONLY test.encuestas
    ADD CONSTRAINT form_encuestas_pkey PRIMARY KEY (id);


--
-- TOC entry 4267 (class 2606 OID 22461)
-- Name: ia_base_conocimiento ia_base_conocimiento_pkey; Type: CONSTRAINT; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER TABLE ONLY test.ia_base_conocimiento
    ADD CONSTRAINT ia_base_conocimiento_pkey PRIMARY KEY (id);


--
-- TOC entry 4167 (class 2606 OID 21082)
-- Name: invitaciones invitaciones_pkey; Type: CONSTRAINT; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER TABLE ONLY test.invitaciones
    ADD CONSTRAINT invitaciones_pkey PRIMARY KEY (id);


--
-- TOC entry 4093 (class 2606 OID 19729)
-- Name: agendamientos_link_tokens link_agendamiento_tokens_pkey; Type: CONSTRAINT; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER TABLE ONLY test.agendamientos_link_tokens
    ADD CONSTRAINT link_agendamiento_tokens_pkey PRIMARY KEY (token);


--
-- TOC entry 4071 (class 2606 OID 19492)
-- Name: managers manager_pkey; Type: CONSTRAINT; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER TABLE ONLY test.managers
    ADD CONSTRAINT manager_pkey PRIMARY KEY (id);


--
-- TOC entry 4202 (class 2606 OID 21609)
-- Name: mensajes_whatsapp_chat_estado mensajes_whatsapp_chat_estado_pkey; Type: CONSTRAINT; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER TABLE ONLY test.mensajes_whatsapp_chat_estado
    ADD CONSTRAINT mensajes_whatsapp_chat_estado_pkey PRIMARY KEY (telefono);


--
-- TOC entry 4101 (class 2606 OID 20109)
-- Name: mensajes_whatsapp mensajes_whatsapp_message_id_meta_key; Type: CONSTRAINT; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER TABLE ONLY test.mensajes_whatsapp
    ADD CONSTRAINT mensajes_whatsapp_message_id_meta_key UNIQUE (message_id_meta);


--
-- TOC entry 4103 (class 2606 OID 21160)
-- Name: mensajes_whatsapp mensajes_whatsapp_message_id_meta_unique; Type: CONSTRAINT; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER TABLE ONLY test.mensajes_whatsapp
    ADD CONSTRAINT mensajes_whatsapp_message_id_meta_unique UNIQUE (message_id_meta);


--
-- TOC entry 4105 (class 2606 OID 20107)
-- Name: mensajes_whatsapp mensajes_whatsapp_pkey; Type: CONSTRAINT; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER TABLE ONLY test.mensajes_whatsapp
    ADD CONSTRAINT mensajes_whatsapp_pkey PRIMARY KEY (id);


--
-- TOC entry 4109 (class 2606 OID 20282)
-- Name: diagnostico_modelo modelo_evaluacion_pkey; Type: CONSTRAINT; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER TABLE ONLY test.diagnostico_modelo
    ADD CONSTRAINT modelo_evaluacion_pkey PRIMARY KEY (id);


--
-- TOC entry 4134 (class 2606 OID 20787)
-- Name: diagnostico_variable_valor modelo_variable_valor_pkey; Type: CONSTRAINT; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER TABLE ONLY test.diagnostico_variable_valor
    ADD CONSTRAINT modelo_variable_valor_pkey PRIMARY KEY (id);


--
-- TOC entry 4177 (class 2606 OID 21237)
-- Name: participante_tipo participante_tipo_codigo_key; Type: CONSTRAINT; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER TABLE ONLY test.participante_tipo
    ADD CONSTRAINT participante_tipo_codigo_key UNIQUE (codigo);


--
-- TOC entry 4179 (class 2606 OID 21235)
-- Name: participante_tipo participante_tipo_pkey; Type: CONSTRAINT; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER TABLE ONLY test.participante_tipo
    ADD CONSTRAINT participante_tipo_pkey PRIMARY KEY (id);


--
-- TOC entry 4075 (class 2606 OID 19534)
-- Name: aspirantes_perfil perfil_creador_creador_id_key; Type: CONSTRAINT; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER TABLE ONLY test.aspirantes_perfil
    ADD CONSTRAINT perfil_creador_creador_id_key UNIQUE (aspirante_id);


--
-- TOC entry 4078 (class 2606 OID 19532)
-- Name: aspirantes_perfil perfil_creador_pkey; Type: CONSTRAINT; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER TABLE ONLY test.aspirantes_perfil
    ADD CONSTRAINT perfil_creador_pkey PRIMARY KEY (id);


--
-- TOC entry 4171 (class 2606 OID 21190)
-- Name: portal_access_tokens portal_access_tokens_pkey; Type: CONSTRAINT; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER TABLE ONLY test.portal_access_tokens
    ADD CONSTRAINT portal_access_tokens_pkey PRIMARY KEY (id);


--
-- TOC entry 4173 (class 2606 OID 21192)
-- Name: portal_access_tokens portal_access_tokens_token_key; Type: CONSTRAINT; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER TABLE ONLY test.portal_access_tokens
    ADD CONSTRAINT portal_access_tokens_token_key UNIQUE (token);


--
-- TOC entry 4081 (class 2606 OID 19556)
-- Name: administradores_roles roles_nombre_key; Type: CONSTRAINT; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER TABLE ONLY test.administradores_roles
    ADD CONSTRAINT roles_nombre_key UNIQUE (nombre);


--
-- TOC entry 4083 (class 2606 OID 19554)
-- Name: administradores_roles roles_pkey; Type: CONSTRAINT; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER TABLE ONLY test.administradores_roles
    ADD CONSTRAINT roles_pkey PRIMARY KEY (id);


--
-- TOC entry 4087 (class 2606 OID 19564)
-- Name: creadores_performance_seguimiento seguimiento_creadores_pkey; Type: CONSTRAINT; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER TABLE ONLY test.creadores_performance_seguimiento
    ADD CONSTRAINT seguimiento_creadores_pkey PRIMARY KEY (id);


--
-- TOC entry 4117 (class 2606 OID 20645)
-- Name: diagnostico_score_categoria talento_score_categoria_pkey; Type: CONSTRAINT; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER TABLE ONLY test.diagnostico_score_categoria
    ADD CONSTRAINT talento_score_categoria_pkey PRIMARY KEY (id);


--
-- TOC entry 4123 (class 2606 OID 20665)
-- Name: diagnostico_score_general talento_score_general_pkey; Type: CONSTRAINT; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER TABLE ONLY test.diagnostico_score_general
    ADD CONSTRAINT talento_score_general_pkey PRIMARY KEY (id);


--
-- TOC entry 4127 (class 2606 OID 20676)
-- Name: diagnostico_interpretacion_categoria talento_script_categoria_pkey; Type: CONSTRAINT; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER TABLE ONLY test.diagnostico_interpretacion_categoria
    ADD CONSTRAINT talento_script_categoria_pkey PRIMARY KEY (id);


--
-- TOC entry 4107 (class 2606 OID 20128)
-- Name: agendamientos_tipo tipos_agendamiento_pkey; Type: CONSTRAINT; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER TABLE ONLY test.agendamientos_tipo
    ADD CONSTRAINT tipos_agendamiento_pkey PRIMARY KEY (id);


--
-- TOC entry 4330 (class 2606 OID 22798)
-- Name: creadores_capacitaciones_seguimiento uq_capacitacion_creador; Type: CONSTRAINT; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER TABLE ONLY test.creadores_capacitaciones_seguimiento
    ADD CONSTRAINT uq_capacitacion_creador UNIQUE (creador_tiktok_id, id_capacitacion);


--
-- TOC entry 4129 (class 2606 OID 20986)
-- Name: diagnostico_interpretacion_categoria uq_categoria_escala_nivel; Type: CONSTRAINT; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER TABLE ONLY test.diagnostico_interpretacion_categoria
    ADD CONSTRAINT uq_categoria_escala_nivel UNIQUE (categoria_id, escala, nivel);


--
-- TOC entry 4220 (class 2606 OID 22095)
-- Name: creadores_detalle uq_creador_detalle; Type: CONSTRAINT; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER TABLE ONLY test.creadores_detalle
    ADD CONSTRAINT uq_creador_detalle UNIQUE (creador_id);


--
-- TOC entry 4231 (class 2606 OID 22175)
-- Name: creadores_reporte_integral uq_creador_periodo_reporte; Type: CONSTRAINT; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER TABLE ONLY test.creadores_reporte_integral
    ADD CONSTRAINT uq_creador_periodo_reporte UNIQUE (creador_tiktok_id, periodo_inicio, periodo_fin);


--
-- TOC entry 4215 (class 2606 OID 22045)
-- Name: creadores uq_creadores_aspirante_id; Type: CONSTRAINT; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER TABLE ONLY test.creadores
    ADD CONSTRAINT uq_creadores_aspirante_id UNIQUE (aspirante_id);


--
-- TOC entry 4323 (class 2606 OID 22783)
-- Name: creadores_capacitaciones uq_creadores_capacitaciones_nombre; Type: CONSTRAINT; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER TABLE ONLY test.creadores_capacitaciones
    ADD CONSTRAINT uq_creadores_capacitaciones_nombre UNIQUE (nombre);


--
-- TOC entry 4211 (class 2606 OID 21898)
-- Name: creadores_perfil_respuesta uq_creadores_perfil_respuesta_creador_variable; Type: CONSTRAINT; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER TABLE ONLY test.creadores_perfil_respuesta
    ADD CONSTRAINT uq_creadores_perfil_respuesta_creador_variable UNIQUE (creador_id, variable_id);


--
-- TOC entry 4237 (class 2606 OID 22229)
-- Name: creadores_metas_mensuales uq_meta_creador_periodo; Type: CONSTRAINT; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER TABLE ONLY test.creadores_metas_mensuales
    ADD CONSTRAINT uq_meta_creador_periodo UNIQUE (creador_id, periodo_inicio, periodo_fin);


--
-- TOC entry 4318 (class 2606 OID 22747)
-- Name: creadores_performance_observaciones uq_performance_observacion_creador_periodo; Type: CONSTRAINT; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER TABLE ONLY test.creadores_performance_observaciones
    ADD CONSTRAINT uq_performance_observacion_creador_periodo UNIQUE (creador_tiktok_id, periodo_inicio, periodo_fin);


--
-- TOC entry 4302 (class 2606 OID 22699)
-- Name: creadores_performance_tablero_creadores uq_tablero_creador_corte; Type: CONSTRAINT; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER TABLE ONLY test.creadores_performance_tablero_creadores
    ADD CONSTRAINT uq_tablero_creador_corte UNIQUE (id_corte, creador_tiktok_id);


--
-- TOC entry 4308 (class 2606 OID 22724)
-- Name: creadores_performance_tablero_semanas uq_tablero_semana_orden; Type: CONSTRAINT; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER TABLE ONLY test.creadores_performance_tablero_semanas
    ADD CONSTRAINT uq_tablero_semana_orden UNIQUE (id_tablero_creador, semana_orden);


--
-- TOC entry 4310 (class 2606 OID 22726)
-- Name: creadores_performance_tablero_semanas uq_tablero_semana_periodo; Type: CONSTRAINT; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER TABLE ONLY test.creadores_performance_tablero_semanas
    ADD CONSTRAINT uq_tablero_semana_periodo UNIQUE (id_tablero_creador, periodo_inicio, periodo_fin);


--
-- TOC entry 4247 (class 2606 OID 22333)
-- Name: whatsapp_flujos whatsapp_flujos_pkey; Type: CONSTRAINT; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER TABLE ONLY test.whatsapp_flujos
    ADD CONSTRAINT whatsapp_flujos_pkey PRIMARY KEY (numero);


--
-- TOC entry 4089 (class 2606 OID 19695)
-- Name: zona_horaria zona_horaria_codigo_key; Type: CONSTRAINT; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER TABLE ONLY test.zona_horaria
    ADD CONSTRAINT zona_horaria_codigo_key UNIQUE (codigo);


--
-- TOC entry 4091 (class 2606 OID 19693)
-- Name: zona_horaria zona_horaria_pkey; Type: CONSTRAINT; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER TABLE ONLY test.zona_horaria
    ADD CONSTRAINT zona_horaria_pkey PRIMARY KEY (id);


--
-- TOC entry 4049 (class 1259 OID 19396)
-- Name: agendamientos_google_event_id_idx; Type: INDEX; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE INDEX agendamientos_google_event_id_idx ON test.agendamientos USING btree (google_event_id);


--
-- TOC entry 4052 (class 1259 OID 19404)
-- Name: agendamientos_participantes_agendamiento_id_idx; Type: INDEX; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE INDEX agendamientos_participantes_agendamiento_id_idx ON test.agendamientos_participantes USING btree (agendamiento_id);


--
-- TOC entry 4061 (class 1259 OID 19443)
-- Name: creadores_id_idx; Type: INDEX; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE INDEX creadores_id_idx ON test.aspirantes USING btree (id);


--
-- TOC entry 4055 (class 1259 OID 21361)
-- Name: idx_agendamientos_participantes_agendamiento; Type: INDEX; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE INDEX idx_agendamientos_participantes_agendamiento ON test.agendamientos_participantes USING btree (agendamiento_id);


--
-- TOC entry 4056 (class 1259 OID 21362)
-- Name: idx_agendamientos_participantes_tipo_participante; Type: INDEX; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE INDEX idx_agendamientos_participantes_tipo_participante ON test.agendamientos_participantes USING btree (participante_tipo_id, participante_id);


--
-- TOC entry 4321 (class 1259 OID 22807)
-- Name: idx_capacitaciones_activa_orden; Type: INDEX; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE INDEX idx_capacitaciones_activa_orden ON test.creadores_capacitaciones USING btree (activa, orden);


--
-- TOC entry 4326 (class 1259 OID 22804)
-- Name: idx_capacitaciones_seguimiento_creador; Type: INDEX; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE INDEX idx_capacitaciones_seguimiento_creador ON test.creadores_capacitaciones_seguimiento USING btree (creador_tiktok_id);


--
-- TOC entry 4327 (class 1259 OID 22806)
-- Name: idx_capacitaciones_seguimiento_estado; Type: INDEX; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE INDEX idx_capacitaciones_seguimiento_estado ON test.creadores_capacitaciones_seguimiento USING btree (estado);


--
-- TOC entry 4328 (class 1259 OID 22805)
-- Name: idx_capacitaciones_seguimiento_manager; Type: INDEX; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE INDEX idx_capacitaciones_seguimiento_manager ON test.creadores_capacitaciones_seguimiento USING btree (manager);


--
-- TOC entry 4199 (class 1259 OID 21611)
-- Name: idx_chat_estado_last_read; Type: INDEX; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE INDEX idx_chat_estado_last_read ON test.mensajes_whatsapp_chat_estado USING btree (last_read_at);


--
-- TOC entry 4200 (class 1259 OID 21621)
-- Name: idx_chat_estado_tel; Type: INDEX; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE INDEX idx_chat_estado_tel ON test.mensajes_whatsapp_chat_estado USING btree (telefono);


--
-- TOC entry 4125 (class 1259 OID 20924)
-- Name: idx_diag_interp_lookup; Type: INDEX; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE INDEX idx_diag_interp_lookup ON test.diagnostico_interpretacion_categoria USING btree (categoria_id, escala, nivel) INCLUDE (script);


--
-- TOC entry 4113 (class 1259 OID 20919)
-- Name: idx_diag_score_cat_creador_modelo; Type: INDEX; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE INDEX idx_diag_score_cat_creador_modelo ON test.diagnostico_score_categoria USING btree (aspirante_id, modelo_id) INCLUDE (categoria_id, score_categoria, nivel);


--
-- TOC entry 4114 (class 1259 OID 20920)
-- Name: idx_diag_score_cat_modelo; Type: INDEX; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE INDEX idx_diag_score_cat_modelo ON test.diagnostico_score_categoria USING btree (modelo_id);


--
-- TOC entry 4115 (class 1259 OID 20921)
-- Name: idx_diag_score_cat_modelo_categoria; Type: INDEX; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE INDEX idx_diag_score_cat_modelo_categoria ON test.diagnostico_score_categoria USING btree (modelo_id, categoria_id);


--
-- TOC entry 4119 (class 1259 OID 20915)
-- Name: idx_diag_score_creador; Type: INDEX; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE INDEX idx_diag_score_creador ON test.diagnostico_score_general USING btree (aspirante_id) INCLUDE (modelo_id, puntaje_total, nivel, created_at);


--
-- TOC entry 4120 (class 1259 OID 20916)
-- Name: idx_diag_score_modelo; Type: INDEX; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE INDEX idx_diag_score_modelo ON test.diagnostico_score_general USING btree (modelo_id);


--
-- TOC entry 4121 (class 1259 OID 20917)
-- Name: idx_diag_score_modelo_nivel; Type: INDEX; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE INDEX idx_diag_score_modelo_nivel ON test.diagnostico_score_general USING btree (modelo_id, nivel);


--
-- TOC entry 4138 (class 1259 OID 20912)
-- Name: idx_diag_variable_categoria; Type: INDEX; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE INDEX idx_diag_variable_categoria ON test.diagnostico_variable USING btree (categoria_id) INCLUDE (peso_variable);


--
-- TOC entry 4139 (class 1259 OID 20911)
-- Name: idx_diag_variable_encuesta_activa_orden; Type: INDEX; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE INDEX idx_diag_variable_encuesta_activa_orden ON test.diagnostico_variable USING btree (encuesta_id, activa, orden) INCLUDE (id, categoria_id, peso_variable, tipo_form, campo_db);


--
-- TOC entry 4140 (class 1259 OID 20913)
-- Name: idx_diag_variable_perfil; Type: INDEX; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE INDEX idx_diag_variable_perfil ON test.diagnostico_variable USING btree (encuesta_id) WHERE ((encuesta_id = 0) AND (campo_db IS NOT NULL) AND ((tipo)::text <> 'texto'::text));


--
-- TOC entry 4152 (class 1259 OID 20950)
-- Name: idx_diagnostico_categoria_activo; Type: INDEX; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE INDEX idx_diagnostico_categoria_activo ON test.diagnostico_categoria USING btree (activo);


--
-- TOC entry 4131 (class 1259 OID 20905)
-- Name: idx_dvv_variable_rango_opt; Type: INDEX; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE INDEX idx_dvv_variable_rango_opt ON test.diagnostico_variable_valor USING btree (variable_id, min_val, max_val) INCLUDE (id);


--
-- TOC entry 4132 (class 1259 OID 20900)
-- Name: idx_dvv_variable_score; Type: INDEX; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE INDEX idx_dvv_variable_score ON test.diagnostico_variable_valor USING btree (variable_id, score);


--
-- TOC entry 4268 (class 1259 OID 22471)
-- Name: idx_ia_bc_activo_mod_cat_prioridad; Type: INDEX; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE INDEX idx_ia_bc_activo_mod_cat_prioridad ON test.ia_base_conocimiento USING btree (modulo, categoria, prioridad, updated_at DESC, id DESC) WHERE (activo = true);


--
-- TOC entry 4269 (class 1259 OID 22472)
-- Name: idx_ia_bc_activo_modulo; Type: INDEX; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE INDEX idx_ia_bc_activo_modulo ON test.ia_base_conocimiento USING btree (modulo, prioridad, updated_at DESC, id DESC) WHERE (activo = true);


--
-- TOC entry 4270 (class 1259 OID 22473)
-- Name: idx_ia_bc_activo_orden; Type: INDEX; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE INDEX idx_ia_bc_activo_orden ON test.ia_base_conocimiento USING btree (prioridad, updated_at DESC, id DESC) WHERE (activo = true);


--
-- TOC entry 4271 (class 1259 OID 22474)
-- Name: idx_ia_bc_mod_cat_sub_titulo; Type: INDEX; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE UNIQUE INDEX idx_ia_bc_mod_cat_sub_titulo ON test.ia_base_conocimiento USING btree (modulo, categoria, COALESCE(subcategoria, ''::character varying), titulo) WHERE (activo = true);


--
-- TOC entry 4272 (class 1259 OID 22557)
-- Name: idx_ia_bc_resumen_trgm; Type: INDEX; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE INDEX idx_ia_bc_resumen_trgm ON test.ia_base_conocimiento USING gin (resumen public.gin_trgm_ops);


--
-- TOC entry 4273 (class 1259 OID 22556)
-- Name: idx_ia_bc_titulo_trgm; Type: INDEX; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE INDEX idx_ia_bc_titulo_trgm ON test.ia_base_conocimiento USING gin (titulo public.gin_trgm_ops);


--
-- TOC entry 4163 (class 1259 OID 21099)
-- Name: idx_invitaciones_creador_id; Type: INDEX; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE INDEX idx_invitaciones_creador_id ON test.invitaciones USING btree (aspirante_id);


--
-- TOC entry 4164 (class 1259 OID 21100)
-- Name: idx_invitaciones_estado_invitacion; Type: INDEX; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE INDEX idx_invitaciones_estado_invitacion ON test.invitaciones USING btree (estado_invitacion);


--
-- TOC entry 4165 (class 1259 OID 21101)
-- Name: idx_invitaciones_estado_tiktok; Type: INDEX; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE INDEX idx_invitaciones_estado_tiktok ON test.invitaciones USING btree (estado_tiktok);


--
-- TOC entry 4156 (class 1259 OID 20980)
-- Name: idx_modelo_categoria_categoria; Type: INDEX; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE INDEX idx_modelo_categoria_categoria ON test.diagnostico_modelo_categoria USING btree (categoria_id);


--
-- TOC entry 4157 (class 1259 OID 20979)
-- Name: idx_modelo_categoria_modelo; Type: INDEX; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE INDEX idx_modelo_categoria_modelo ON test.diagnostico_modelo_categoria USING btree (modelo_id);


--
-- TOC entry 4096 (class 1259 OID 21620)
-- Name: idx_msg_direccion; Type: INDEX; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE INDEX idx_msg_direccion ON test.mensajes_whatsapp USING btree (direccion);


--
-- TOC entry 4097 (class 1259 OID 21619)
-- Name: idx_msg_tel_fecha; Type: INDEX; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE INDEX idx_msg_tel_fecha ON test.mensajes_whatsapp USING btree (telefono, fecha DESC);


--
-- TOC entry 4098 (class 1259 OID 21631)
-- Name: idx_mw_telefono_direccion_fecha; Type: INDEX; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE INDEX idx_mw_telefono_direccion_fecha ON test.mensajes_whatsapp USING btree (telefono, direccion, fecha DESC);


--
-- TOC entry 4099 (class 1259 OID 21630)
-- Name: idx_mw_telefono_fecha; Type: INDEX; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE INDEX idx_mw_telefono_fecha ON test.mensajes_whatsapp USING btree (telefono, fecha DESC);


--
-- TOC entry 4250 (class 1259 OID 22400)
-- Name: idx_perf_acciones_estado; Type: INDEX; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE INDEX idx_perf_acciones_estado ON test.creadores_performance_acciones USING btree (estado);


--
-- TOC entry 4253 (class 1259 OID 22401)
-- Name: idx_perf_alertas_creador; Type: INDEX; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE INDEX idx_perf_alertas_creador ON test.creadores_performance_alertas USING btree (creador_id);


--
-- TOC entry 4261 (class 1259 OID 22403)
-- Name: idx_perf_resumen_creador; Type: INDEX; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE INDEX idx_perf_resumen_creador ON test.creadores_performance_resumen USING btree (creador_id);


--
-- TOC entry 4258 (class 1259 OID 22402)
-- Name: idx_perf_score_creador; Type: INDEX; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE INDEX idx_perf_score_creador ON test.creadores_performance_score USING btree (creador_id);


--
-- TOC entry 4084 (class 1259 OID 22398)
-- Name: idx_perf_seg_creador; Type: INDEX; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE INDEX idx_perf_seg_creador ON test.creadores_performance_seguimiento USING btree (creador_id);


--
-- TOC entry 4085 (class 1259 OID 22399)
-- Name: idx_perf_seg_fecha; Type: INDEX; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE INDEX idx_perf_seg_fecha ON test.creadores_performance_seguimiento USING btree (fecha_seguimiento);


--
-- TOC entry 4285 (class 1259 OID 22664)
-- Name: idx_performance_objetivos_activos; Type: INDEX; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE INDEX idx_performance_objetivos_activos ON test.creadores_performance_objetivos USING btree (nivel_aplicacion, activo);


--
-- TOC entry 4286 (class 1259 OID 22665)
-- Name: idx_performance_objetivos_creador; Type: INDEX; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE INDEX idx_performance_objetivos_creador ON test.creadores_performance_objetivos USING btree (creador_tiktok_id, creador_id);


--
-- TOC entry 4287 (class 1259 OID 22667)
-- Name: idx_performance_objetivos_grupo; Type: INDEX; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE INDEX idx_performance_objetivos_grupo ON test.creadores_performance_objetivos USING btree (grupo);


--
-- TOC entry 4288 (class 1259 OID 22666)
-- Name: idx_performance_objetivos_manager; Type: INDEX; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE INDEX idx_performance_objetivos_manager ON test.creadores_performance_objetivos USING btree (manager);


--
-- TOC entry 4289 (class 1259 OID 22668)
-- Name: idx_performance_objetivos_rango; Type: INDEX; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE INDEX idx_performance_objetivos_rango ON test.creadores_performance_objetivos USING btree (id_rango);


--
-- TOC entry 4313 (class 1259 OID 22751)
-- Name: idx_performance_observaciones_activo; Type: INDEX; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE INDEX idx_performance_observaciones_activo ON test.creadores_performance_observaciones USING btree (activo);


--
-- TOC entry 4314 (class 1259 OID 22748)
-- Name: idx_performance_observaciones_creador_periodo; Type: INDEX; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE INDEX idx_performance_observaciones_creador_periodo ON test.creadores_performance_observaciones USING btree (creador_tiktok_id, periodo_inicio, periodo_fin);


--
-- TOC entry 4315 (class 1259 OID 22750)
-- Name: idx_performance_observaciones_grupo; Type: INDEX; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE INDEX idx_performance_observaciones_grupo ON test.creadores_performance_observaciones USING btree (grupo);


--
-- TOC entry 4316 (class 1259 OID 22749)
-- Name: idx_performance_observaciones_manager; Type: INDEX; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE INDEX idx_performance_observaciones_manager ON test.creadores_performance_observaciones USING btree (manager);


--
-- TOC entry 4278 (class 1259 OID 22628)
-- Name: idx_rangos_diamantes_activo; Type: INDEX; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE INDEX idx_rangos_diamantes_activo ON test.creadores_performance_rangos_diamantes USING btree (activo, diamantes_min, diamantes_max);


--
-- TOC entry 4223 (class 1259 OID 22754)
-- Name: idx_reporte_integral_agente; Type: INDEX; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE INDEX idx_reporte_integral_agente ON test.creadores_reporte_integral USING btree (agente);


--
-- TOC entry 4224 (class 1259 OID 22752)
-- Name: idx_reporte_integral_creador_periodo; Type: INDEX; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE INDEX idx_reporte_integral_creador_periodo ON test.creadores_reporte_integral USING btree (creador_tiktok_id, periodo_inicio, periodo_fin);


--
-- TOC entry 4225 (class 1259 OID 22755)
-- Name: idx_reporte_integral_grupo; Type: INDEX; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE INDEX idx_reporte_integral_grupo ON test.creadores_reporte_integral USING btree (grupo);


--
-- TOC entry 4226 (class 1259 OID 22758)
-- Name: idx_reporte_integral_importacion; Type: INDEX; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE INDEX idx_reporte_integral_importacion ON test.creadores_reporte_integral USING btree (importacion_id);


--
-- TOC entry 4227 (class 1259 OID 22756)
-- Name: idx_reporte_integral_periodo; Type: INDEX; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE INDEX idx_reporte_integral_periodo ON test.creadores_reporte_integral USING btree (periodo_inicio, periodo_fin);


--
-- TOC entry 4228 (class 1259 OID 22757)
-- Name: idx_reporte_integral_tipo_periodo; Type: INDEX; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE INDEX idx_reporte_integral_tipo_periodo ON test.creadores_reporte_integral USING btree (tipo_periodo);


--
-- TOC entry 4229 (class 1259 OID 22753)
-- Name: idx_reporte_integral_usuario_tiktok; Type: INDEX; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE INDEX idx_reporte_integral_usuario_tiktok ON test.creadores_reporte_integral USING btree (usuario_tiktok);


--
-- TOC entry 4143 (class 1259 OID 20933)
-- Name: idx_score_creador_cover; Type: INDEX; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE INDEX idx_score_creador_cover ON test.diagnostico_score_variable USING btree (aspirante_id) INCLUDE (variable_id, valor, valor_id);


--
-- TOC entry 4144 (class 1259 OID 20936)
-- Name: idx_score_valor; Type: INDEX; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE INDEX idx_score_valor ON test.diagnostico_score_variable USING btree (valor);


--
-- TOC entry 4145 (class 1259 OID 20937)
-- Name: idx_score_valor_id; Type: INDEX; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE INDEX idx_score_valor_id ON test.diagnostico_score_variable USING btree (valor_id);


--
-- TOC entry 4146 (class 1259 OID 20938)
-- Name: idx_score_variable_creador; Type: INDEX; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE INDEX idx_score_variable_creador ON test.diagnostico_score_variable USING btree (variable_id, aspirante_id);


--
-- TOC entry 4147 (class 1259 OID 20934)
-- Name: idx_score_variable_valor; Type: INDEX; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE INDEX idx_score_variable_valor ON test.diagnostico_score_variable USING btree (variable_id, valor);


--
-- TOC entry 4148 (class 1259 OID 20935)
-- Name: idx_score_variable_valorid; Type: INDEX; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE INDEX idx_score_variable_valorid ON test.diagnostico_score_variable USING btree (variable_id, valor_id);


--
-- TOC entry 4292 (class 1259 OID 22683)
-- Name: idx_tablero_cortes_estado; Type: INDEX; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE INDEX idx_tablero_cortes_estado ON test.creadores_performance_tablero_cortes USING btree (estado);


--
-- TOC entry 4293 (class 1259 OID 22684)
-- Name: idx_tablero_cortes_periodo; Type: INDEX; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE INDEX idx_tablero_cortes_periodo ON test.creadores_performance_tablero_cortes USING btree (periodo_corte_fin);


--
-- TOC entry 4296 (class 1259 OID 22705)
-- Name: idx_tablero_creadores_corte; Type: INDEX; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE INDEX idx_tablero_creadores_corte ON test.creadores_performance_tablero_creadores USING btree (id_corte);


--
-- TOC entry 4297 (class 1259 OID 22707)
-- Name: idx_tablero_creadores_grupo; Type: INDEX; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE INDEX idx_tablero_creadores_grupo ON test.creadores_performance_tablero_creadores USING btree (grupo);


--
-- TOC entry 4298 (class 1259 OID 22706)
-- Name: idx_tablero_creadores_manager; Type: INDEX; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE INDEX idx_tablero_creadores_manager ON test.creadores_performance_tablero_creadores USING btree (manager_actual);


--
-- TOC entry 4299 (class 1259 OID 22709)
-- Name: idx_tablero_creadores_rango; Type: INDEX; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE INDEX idx_tablero_creadores_rango ON test.creadores_performance_tablero_creadores USING btree (rango_codigo);


--
-- TOC entry 4300 (class 1259 OID 22708)
-- Name: idx_tablero_creadores_tiktok; Type: INDEX; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE INDEX idx_tablero_creadores_tiktok ON test.creadores_performance_tablero_creadores USING btree (creador_tiktok_id);


--
-- TOC entry 4305 (class 1259 OID 22732)
-- Name: idx_tablero_semanas_creador_orden; Type: INDEX; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE INDEX idx_tablero_semanas_creador_orden ON test.creadores_performance_tablero_semanas USING btree (id_tablero_creador, semana_orden);


--
-- TOC entry 4306 (class 1259 OID 22733)
-- Name: idx_tablero_semanas_periodo; Type: INDEX; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE INDEX idx_tablero_semanas_periodo ON test.creadores_performance_tablero_semanas USING btree (periodo_inicio, periodo_fin);


--
-- TOC entry 4072 (class 1259 OID 19537)
-- Name: perfil_creador_apto_idx; Type: INDEX; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE INDEX perfil_creador_apto_idx ON test.aspirantes_perfil USING btree (apto);


--
-- TOC entry 4073 (class 1259 OID 19536)
-- Name: perfil_creador_creador_id_idx; Type: INDEX; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE UNIQUE INDEX perfil_creador_creador_id_idx ON test.aspirantes_perfil USING btree (aspirante_id);


--
-- TOC entry 4076 (class 1259 OID 19538)
-- Name: perfil_creador_estado_idx; Type: INDEX; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE INDEX perfil_creador_estado_idx ON test.aspirantes_perfil USING btree (estado);


--
-- TOC entry 4079 (class 1259 OID 19535)
-- Name: perfil_creador_usuario_idx; Type: INDEX; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE INDEX perfil_creador_usuario_idx ON test.aspirantes_perfil USING btree (usuario);


--
-- TOC entry 4216 (class 1259 OID 22188)
-- Name: uq_creadores_creador_tiktok_id; Type: INDEX; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE UNIQUE INDEX uq_creadores_creador_tiktok_id ON test.creadores USING btree (creador_tiktok_id);


--
-- TOC entry 4198 (class 1259 OID 22254)
-- Name: uq_creadores_encuesta_inicial_creador_id; Type: INDEX; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE UNIQUE INDEX uq_creadores_encuesta_inicial_creador_id ON test.creadores_encuesta_inicial USING btree (creador_id);


--
-- TOC entry 4203 (class 1259 OID 21632)
-- Name: uq_mw_chat_estado_telefono; Type: INDEX; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE UNIQUE INDEX uq_mw_chat_estado_telefono ON test.mensajes_whatsapp_chat_estado USING btree (telefono);


--
-- TOC entry 4279 (class 1259 OID 22627)
-- Name: uq_rangos_diamantes_codigo; Type: INDEX; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE UNIQUE INDEX uq_rangos_diamantes_codigo ON test.creadores_performance_rangos_diamantes USING btree (codigo_rango);


--
-- TOC entry 4282 (class 1259 OID 22644)
-- Name: uq_reglas_estado_codigo; Type: INDEX; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE UNIQUE INDEX uq_reglas_estado_codigo ON test.creadores_performance_reglas_estado USING btree (tipo_regla, codigo_estado, tipo_periodo);


--
-- TOC entry 4174 (class 1259 OID 22258)
-- Name: uq_token_activo_aspirante; Type: INDEX; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE UNIQUE INDEX uq_token_activo_aspirante ON test.portal_access_tokens USING btree (aspirante_id, tipo_portal) WHERE (((estado)::text = 'activo'::text) AND ((tipo_portal)::text = 'aspirante'::text));


--
-- TOC entry 4175 (class 1259 OID 22259)
-- Name: uq_token_activo_creador; Type: INDEX; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE UNIQUE INDEX uq_token_activo_creador ON test.portal_access_tokens USING btree (creador_id, tipo_portal) WHERE (((estado)::text = 'activo'::text) AND ((tipo_portal)::text = 'creador'::text));


--
-- TOC entry 4130 (class 1259 OID 20923)
-- Name: ux_diag_interp_categoria; Type: INDEX; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE UNIQUE INDEX ux_diag_interp_categoria ON test.diagnostico_interpretacion_categoria USING btree (categoria_id, escala, nivel);


--
-- TOC entry 4118 (class 1259 OID 20918)
-- Name: ux_diag_score_cat_creador_modelo; Type: INDEX; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE UNIQUE INDEX ux_diag_score_cat_creador_modelo ON test.diagnostico_score_categoria USING btree (aspirante_id, modelo_id, categoria_id);


--
-- TOC entry 4124 (class 1259 OID 20914)
-- Name: ux_diag_score_creador_modelo; Type: INDEX; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE UNIQUE INDEX ux_diag_score_creador_modelo ON test.diagnostico_score_general USING btree (aspirante_id, modelo_id);


--
-- TOC entry 4153 (class 1259 OID 20949)
-- Name: ux_diagnostico_categoria_nombre; Type: INDEX; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE UNIQUE INDEX ux_diagnostico_categoria_nombre ON test.diagnostico_categoria USING btree (nombre);


--
-- TOC entry 4110 (class 1259 OID 21104)
-- Name: ux_diagnostico_modelo_unico_activo; Type: INDEX; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE UNIQUE INDEX ux_diagnostico_modelo_unico_activo ON test.diagnostico_modelo USING btree (activo) WHERE (activo = true);


--
-- TOC entry 4158 (class 1259 OID 20981)
-- Name: ux_modelo_categoria_modelo_categoria; Type: INDEX; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE UNIQUE INDEX ux_modelo_categoria_modelo_categoria ON test.diagnostico_modelo_categoria USING btree (modelo_id, categoria_id);


--
-- TOC entry 4149 (class 1259 OID 20939)
-- Name: ux_score_creador_variable; Type: INDEX; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE UNIQUE INDEX ux_score_creador_variable ON test.diagnostico_score_variable USING btree (aspirante_id, variable_id);


--
-- TOC entry 4135 (class 1259 OID 20869)
-- Name: ux_variable_valor; Type: INDEX; Schema: test; Owner: whatsapp_db_vsfq_user
--

CREATE UNIQUE INDEX ux_variable_valor ON test.diagnostico_variable_valor USING btree (variable_id, orden);


--
-- TOC entry 4331 (class 2606 OID 21356)
-- Name: agendamientos_participantes fk_agendamientos_participantes_tipo; Type: FK CONSTRAINT; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER TABLE ONLY test.agendamientos_participantes
    ADD CONSTRAINT fk_agendamientos_participantes_tipo FOREIGN KEY (participante_tipo_id) REFERENCES test.participante_tipo(id);


--
-- TOC entry 4342 (class 2606 OID 22799)
-- Name: creadores_capacitaciones_seguimiento fk_capacitacion_seguimiento; Type: FK CONSTRAINT; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER TABLE ONLY test.creadores_capacitaciones_seguimiento
    ADD CONSTRAINT fk_capacitacion_seguimiento FOREIGN KEY (id_capacitacion) REFERENCES test.creadores_capacitaciones(id_capacitacion);


--
-- TOC entry 4334 (class 2606 OID 22409)
-- Name: creadores fk_creadores_categoria; Type: FK CONSTRAINT; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER TABLE ONLY test.creadores
    ADD CONSTRAINT fk_creadores_categoria FOREIGN KEY (categoria_id) REFERENCES test.creadores_categoria(id);


--
-- TOC entry 4335 (class 2606 OID 22293)
-- Name: creadores fk_creadores_estado; Type: FK CONSTRAINT; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER TABLE ONLY test.creadores
    ADD CONSTRAINT fk_creadores_estado FOREIGN KEY (estado_id) REFERENCES test.creadores_estados(id);


--
-- TOC entry 4337 (class 2606 OID 22199)
-- Name: creadores_insights_mensuales fk_insight_reporte; Type: FK CONSTRAINT; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER TABLE ONLY test.creadores_insights_mensuales
    ADD CONSTRAINT fk_insight_reporte FOREIGN KEY (id_reporte) REFERENCES test.creadores_reporte_integral(id_reporte);


--
-- TOC entry 4332 (class 2606 OID 20974)
-- Name: diagnostico_modelo_categoria fk_modelo_categoria_categoria; Type: FK CONSTRAINT; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER TABLE ONLY test.diagnostico_modelo_categoria
    ADD CONSTRAINT fk_modelo_categoria_categoria FOREIGN KEY (categoria_id) REFERENCES test.diagnostico_categoria(id) ON DELETE CASCADE;


--
-- TOC entry 4333 (class 2606 OID 20969)
-- Name: diagnostico_modelo_categoria fk_modelo_categoria_modelo; Type: FK CONSTRAINT; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER TABLE ONLY test.diagnostico_modelo_categoria
    ADD CONSTRAINT fk_modelo_categoria_modelo FOREIGN KEY (modelo_id) REFERENCES test.diagnostico_modelo(id) ON DELETE CASCADE;


--
-- TOC entry 4338 (class 2606 OID 22404)
-- Name: creadores_performance_acciones fk_performance_acciones_seguimiento; Type: FK CONSTRAINT; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER TABLE ONLY test.creadores_performance_acciones
    ADD CONSTRAINT fk_performance_acciones_seguimiento FOREIGN KEY (seguimiento_id) REFERENCES test.creadores_performance_seguimiento(id) ON DELETE CASCADE;


--
-- TOC entry 4339 (class 2606 OID 22659)
-- Name: creadores_performance_objetivos fk_performance_objetivos_rango; Type: FK CONSTRAINT; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER TABLE ONLY test.creadores_performance_objetivos
    ADD CONSTRAINT fk_performance_objetivos_rango FOREIGN KEY (id_rango) REFERENCES test.creadores_performance_rangos_diamantes(id_rango);


--
-- TOC entry 4336 (class 2606 OID 22608)
-- Name: creadores_reporte_integral fk_reporte_integral_importacion; Type: FK CONSTRAINT; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER TABLE ONLY test.creadores_reporte_integral
    ADD CONSTRAINT fk_reporte_integral_importacion FOREIGN KEY (importacion_id) REFERENCES test.creadores_reporte_importaciones(id_importacion);


--
-- TOC entry 4340 (class 2606 OID 22700)
-- Name: creadores_performance_tablero_creadores fk_tablero_creadores_corte; Type: FK CONSTRAINT; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER TABLE ONLY test.creadores_performance_tablero_creadores
    ADD CONSTRAINT fk_tablero_creadores_corte FOREIGN KEY (id_corte) REFERENCES test.creadores_performance_tablero_cortes(id_corte) ON DELETE CASCADE;


--
-- TOC entry 4341 (class 2606 OID 22727)
-- Name: creadores_performance_tablero_semanas fk_tablero_semanas_creador; Type: FK CONSTRAINT; Schema: test; Owner: whatsapp_db_vsfq_user
--

ALTER TABLE ONLY test.creadores_performance_tablero_semanas
    ADD CONSTRAINT fk_tablero_semanas_creador FOREIGN KEY (id_tablero_creador) REFERENCES test.creadores_performance_tablero_creadores(id_tablero_creador) ON DELETE CASCADE;


-- Completed on 2026-07-22 08:49:56

--
-- PostgreSQL database dump complete
--

\unrestrict k80fjJecMb7lNvzbg1UycdtAHpPhvtGdu0nL3VaB1WCnE0bUe3NRP133cHXhmDj

