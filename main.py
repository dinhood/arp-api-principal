from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import List
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError
import json

app = FastAPI(
    title="Arp Medical API",
    version="1.0.0",
    description="API simples para controle de estoque, insumos e vendas"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = Path(__file__).resolve().parent
DB_NAME = BASE_DIR / "arp_medical.db"

# CEP fixo da empresa para comparação com o fornecedor
CEP_EMPRESA = "01001000"

# URL da API secundária de distância
API_DISTANCIA_URL = "http://host.docker.internal:8001/calcular-distancia"


def get_connection():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn


def agora():
    return datetime.now().strftime("%d/%m/%Y %H:%M:%S")


def limpar_cep(cep: str) -> str:
    return "".join(filter(str.isdigit, cep or ""))


def buscar_endereco_por_cep(cep: str):
    cep_limpo = limpar_cep(cep)

    if len(cep_limpo) != 8:
        raise HTTPException(status_code=400, detail="CEP inválido. Informe 8 dígitos.")

    url = f"https://viacep.com.br/ws/{cep_limpo}/json/"

    try:
        with urlopen(url) as response:
            data = json.loads(response.read().decode("utf-8"))
    except (URLError, HTTPError):
        raise HTTPException(status_code=502, detail="Erro ao consultar o ViaCEP")

    if data.get("erro"):
        raise HTTPException(status_code=404, detail="CEP não encontrado")

    return {
        "cep": data.get("cep", ""),
        "rua": data.get("logradouro", ""),
        "bairro": data.get("bairro", ""),
        "cidade": data.get("localidade", ""),
        "estado": data.get("uf", "")
    }


def chamar_api_distancia(cep_origem: str, cep_destino: str):
    payload = {
        "cep_origem": limpar_cep(cep_origem),
        "cep_destino": limpar_cep(cep_destino)
    }

    body = json.dumps(payload).encode("utf-8")

    request = Request(
        API_DISTANCIA_URL,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST"
    )

    try:
        with urlopen(request) as response:
            resposta = json.loads(response.read().decode("utf-8"))
            return resposta
    except (URLError, HTTPError):
        raise HTTPException(status_code=502, detail="Erro ao consultar a API secundária de distância")


def buscar_insumo_por_id_db(insumo_id: int):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM insumos WHERE id = ?", (insumo_id,))
    insumo = cursor.fetchone()
    conn.close()

    if not insumo:
        return None

    return dict(insumo)


def init_db():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS produtos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL UNIQUE,
            codigo TEXT NOT NULL,
            quantidade INTEGER NOT NULL,
            criado_em TEXT NOT NULL
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS historico_produtos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            produto_id INTEGER NOT NULL UNIQUE,
            produto_nome TEXT NOT NULL,
            data_cadastro TEXT NOT NULL
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS vendas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            produto_id INTEGER NOT NULL,
            produto_nome TEXT NOT NULL,
            quantidade INTEGER NOT NULL,
            data_venda TEXT NOT NULL
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS insumos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            descricao TEXT NOT NULL,
            fornecedor TEXT NOT NULL,
            quantidade INTEGER NOT NULL,
            cep TEXT,
            rua TEXT,
            bairro TEXT,
            cidade TEXT,
            estado TEXT,
            criado_em TEXT NOT NULL
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS producao_insumos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            produto_id INTEGER NOT NULL,
            produto_nome TEXT NOT NULL,
            insumo_id INTEGER NOT NULL,
            insumo_descricao TEXT NOT NULL,
            fornecedor TEXT NOT NULL,
            quantidade_usada INTEGER NOT NULL,
            data_registro TEXT NOT NULL
        )
    """)

    conn.commit()
    conn.close()


init_db()


class InsumoUso(BaseModel):
    insumo_id: int
    quantidade: int = Field(..., gt=0)


class ProdutoCreate(BaseModel):
    nome: str = Field(..., min_length=2)
    codigo: str = Field(..., min_length=1)
    quantidade: int = Field(..., ge=0)
    insumos_usados: List[InsumoUso] = []


class ProdutoUpdate(BaseModel):
    nome: str = Field(..., min_length=2)
    codigo: str = Field(..., min_length=1)
    quantidade: int = Field(..., ge=0)


class VendaCreate(BaseModel):
    produto_id: int
    quantidade: int = Field(..., gt=0)


class InsumoCreate(BaseModel):
    descricao: str = Field(..., min_length=2)
    fornecedor: str = Field(..., min_length=2)
    quantidade: int = Field(..., ge=0)
    cep: str = ""
    rua: str = ""
    bairro: str = ""
    cidade: str = ""
    estado: str = ""


class InsumoUpdate(BaseModel):
    descricao: str = Field(..., min_length=2)
    fornecedor: str = Field(..., min_length=2)
    quantidade: int = Field(..., ge=0)
    cep: str = ""
    rua: str = ""
    bairro: str = ""
    cidade: str = ""
    estado: str = ""


@app.get("/", tags=["Geral"])
def root():
    return {"mensagem": "API Arp Medical funcionando"}


@app.get("/cep/{cep}", tags=["Geral"])
def consultar_cep(cep: str):
    return buscar_endereco_por_cep(cep)


# PRODUTOS

@app.get("/produtos", tags=["Produtos"])
def listar_produtos():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM produtos ORDER BY id DESC")
    produtos = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return produtos


@app.get("/produtos/{produto_id}", tags=["Produtos"])
def buscar_produto(produto_id: int):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM produtos WHERE id = ?", (produto_id,))
    produto = cursor.fetchone()
    conn.close()

    if not produto:
        raise HTTPException(status_code=404, detail="Produto não encontrado")

    return dict(produto)


@app.post("/produtos", tags=["Produtos"])
def criar_produto(produto: ProdutoCreate):
    conn = get_connection()
    cursor = conn.cursor()

    nome_normalizado = produto.nome.strip()

    for item in produto.insumos_usados:
        cursor.execute("SELECT * FROM insumos WHERE id = ?", (item.insumo_id,))
        insumo = cursor.fetchone()

        if not insumo:
            conn.close()
            raise HTTPException(status_code=404, detail=f"Insumo {item.insumo_id} não encontrado")

        insumo = dict(insumo)

        if item.quantidade > insumo["quantidade"]:
            conn.close()
            raise HTTPException(
                status_code=400,
                detail=f"Estoque insuficiente para o insumo {insumo['descricao']}"
            )

    cursor.execute(
        "SELECT * FROM produtos WHERE LOWER(nome) = LOWER(?)",
        (nome_normalizado,)
    )
    produto_existente = cursor.fetchone()

    if produto_existente:
        produto_existente = dict(produto_existente)
        nova_quantidade_produto = produto_existente["quantidade"] + produto.quantidade

        cursor.execute("""
            UPDATE produtos
            SET codigo = ?, quantidade = ?
            WHERE id = ?
        """, (
            produto.codigo,
            nova_quantidade_produto,
            produto_existente["id"]
        ))

        produto_id = produto_existente["id"]
        produto_nome = produto_existente["nome"]
    else:
        cursor.execute("""
            INSERT INTO produtos (nome, codigo, quantidade, criado_em)
            VALUES (?, ?, ?, ?)
        """, (
            nome_normalizado,
            produto.codigo,
            produto.quantidade,
            agora()
        ))
        produto_id = cursor.lastrowid
        produto_nome = nome_normalizado

        cursor.execute("""
            INSERT INTO historico_produtos (produto_id, produto_nome, data_cadastro)
            VALUES (?, ?, ?)
        """, (
            produto_id,
            produto_nome,
            agora()
        ))

    for item in produto.insumos_usados:
        cursor.execute("SELECT * FROM insumos WHERE id = ?", (item.insumo_id,))
        insumo = cursor.fetchone()

        if not insumo:
            conn.close()
            raise HTTPException(status_code=404, detail="Insumo não encontrado na baixa")

        insumo = dict(insumo)
        nova_quantidade_insumo = insumo["quantidade"] - item.quantidade

        cursor.execute("""
            UPDATE insumos
            SET quantidade = ?
            WHERE id = ?
        """, (nova_quantidade_insumo, item.insumo_id))

        cursor.execute("""
            INSERT INTO producao_insumos (
                produto_id,
                produto_nome,
                insumo_id,
                insumo_descricao,
                fornecedor,
                quantidade_usada,
                data_registro
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            produto_id,
            produto_nome,
            insumo["id"],
            insumo["descricao"],
            insumo["fornecedor"],
            item.quantidade,
            agora()
        ))

    conn.commit()

    cursor.execute("SELECT * FROM produtos WHERE id = ?", (produto_id,))
    produto_salvo = dict(cursor.fetchone())

    conn.close()
    return produto_salvo


@app.put("/produtos/{produto_id}", tags=["Produtos"])
def atualizar_produto(produto_id: int, produto: ProdutoUpdate):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM produtos WHERE id = ?", (produto_id,))
    existente = cursor.fetchone()

    if not existente:
        conn.close()
        raise HTTPException(status_code=404, detail="Produto não encontrado")

    cursor.execute("""
        SELECT * FROM produtos
        WHERE LOWER(nome) = LOWER(?) AND id != ?
    """, (produto.nome.strip(), produto_id))
    outro_mesmo_nome = cursor.fetchone()

    if outro_mesmo_nome:
        conn.close()
        raise HTTPException(status_code=400, detail="Já existe outro produto com esse nome")

    cursor.execute("""
        UPDATE produtos
        SET nome = ?, codigo = ?, quantidade = ?
        WHERE id = ?
    """, (
        produto.nome.strip(),
        produto.codigo,
        produto.quantidade,
        produto_id
    ))

    cursor.execute("""
        UPDATE historico_produtos
        SET produto_nome = ?
        WHERE produto_id = ?
    """, (
        produto.nome.strip(),
        produto_id
    ))

    conn.commit()

    cursor.execute("SELECT * FROM produtos WHERE id = ?", (produto_id,))
    atualizado = dict(cursor.fetchone())
    conn.close()
    return atualizado


@app.delete("/produtos/{produto_id}", tags=["Produtos"])
def deletar_produto(produto_id: int):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM produtos WHERE id = ?", (produto_id,))
    produto = cursor.fetchone()

    if not produto:
        conn.close()
        raise HTTPException(status_code=404, detail="Produto não encontrado")

    cursor.execute("DELETE FROM produtos WHERE id = ?", (produto_id,))
    conn.commit()
    conn.close()

    return {"mensagem": "Produto removido com sucesso"}


# VENDAS

@app.post("/vendas", tags=["Vendas"])
def registrar_venda(venda: VendaCreate):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM produtos WHERE id = ?", (venda.produto_id,))
    produto = cursor.fetchone()

    if not produto:
        conn.close()
        raise HTTPException(status_code=404, detail="Produto não encontrado")

    produto = dict(produto)

    if venda.quantidade > produto["quantidade"]:
        conn.close()
        raise HTTPException(status_code=400, detail="Estoque insuficiente")

    nova_quantidade = produto["quantidade"] - venda.quantidade

    cursor.execute("""
        INSERT INTO vendas (produto_id, produto_nome, quantidade, data_venda)
        VALUES (?, ?, ?, ?)
    """, (
        produto["id"],
        produto["nome"],
        venda.quantidade,
        agora()
    ))

    cursor.execute("""
        UPDATE produtos
        SET quantidade = ?
        WHERE id = ?
    """, (nova_quantidade, produto["id"]))

    conn.commit()
    conn.close()

    return {"mensagem": "Venda registrada com sucesso"}


@app.get("/vendas", tags=["Vendas"])
def listar_vendas():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM vendas ORDER BY id DESC")
    vendas = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return vendas


# INSUMOS

@app.get("/insumos", tags=["Insumos"])
def listar_insumos():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM insumos ORDER BY id DESC")
    insumos = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return insumos


@app.get("/insumos/{insumo_id}", tags=["Insumos"])
def buscar_insumo(insumo_id: int):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM insumos WHERE id = ?", (insumo_id,))
    insumo = cursor.fetchone()
    conn.close()

    if not insumo:
        raise HTTPException(status_code=404, detail="Insumo não encontrado")

    return dict(insumo)


@app.get("/insumos/{insumo_id}/distancia", tags=["Insumos"])
def calcular_distancia_fornecedor(insumo_id: int):
    insumo = buscar_insumo_por_id_db(insumo_id)

    if not insumo:
        raise HTTPException(status_code=404, detail="Insumo não encontrado")

    cep_fornecedor = limpar_cep(insumo.get("cep", ""))

    if len(cep_fornecedor) != 8:
        raise HTTPException(status_code=400, detail="Insumo sem CEP válido cadastrado")

    endereco_fornecedor = buscar_endereco_por_cep(cep_fornecedor)
    dados_distancia = chamar_api_distancia(CEP_EMPRESA, cep_fornecedor)

    return {
        "insumo_id": insumo["id"],
        "descricao": insumo["descricao"],
        "fornecedor": insumo["fornecedor"],
        "cep_fornecedor": endereco_fornecedor.get("cep", ""),
        "cidade": endereco_fornecedor.get("cidade", ""),
        "estado": endereco_fornecedor.get("estado", ""),
        "distancia_km": dados_distancia.get("distancia_km", 0),
        "faixa": dados_distancia.get("faixa", "")
    }


@app.post("/insumos", tags=["Insumos"])
def criar_insumo(insumo: InsumoCreate):
    conn = get_connection()
    cursor = conn.cursor()

    descricao_normalizada = insumo.descricao.strip()
    fornecedor_normalizado = insumo.fornecedor.strip()

    cursor.execute("""
        SELECT * FROM insumos
        WHERE LOWER(descricao) = LOWER(?) AND LOWER(fornecedor) = LOWER(?)
    """, (descricao_normalizada, fornecedor_normalizado))
    insumo_existente = cursor.fetchone()

    if insumo_existente:
        insumo_existente = dict(insumo_existente)
        nova_quantidade = insumo_existente["quantidade"] + insumo.quantidade

        cursor.execute("""
            UPDATE insumos
            SET quantidade = ?, cep = ?, rua = ?, bairro = ?, cidade = ?, estado = ?
            WHERE id = ?
        """, (
            nova_quantidade,
            insumo.cep,
            insumo.rua,
            insumo.bairro,
            insumo.cidade,
            insumo.estado,
            insumo_existente["id"]
        ))
        conn.commit()

        cursor.execute("SELECT * FROM insumos WHERE id = ?", (insumo_existente["id"],))
        atualizado = dict(cursor.fetchone())
        conn.close()
        return atualizado

    cursor.execute("""
        INSERT INTO insumos (
            descricao, fornecedor, quantidade, cep, rua, bairro, cidade, estado, criado_em
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        descricao_normalizada,
        fornecedor_normalizado,
        insumo.quantidade,
        insumo.cep,
        insumo.rua,
        insumo.bairro,
        insumo.cidade,
        insumo.estado,
        agora()
    ))
    conn.commit()
    insumo_id = cursor.lastrowid

    cursor.execute("SELECT * FROM insumos WHERE id = ?", (insumo_id,))
    novo_insumo = dict(cursor.fetchone())

    conn.close()
    return novo_insumo


@app.put("/insumos/{insumo_id}", tags=["Insumos"])
def atualizar_insumo(insumo_id: int, insumo: InsumoUpdate):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM insumos WHERE id = ?", (insumo_id,))
    existente = cursor.fetchone()

    if not existente:
        conn.close()
        raise HTTPException(status_code=404, detail="Insumo não encontrado")

    cursor.execute("""
        SELECT * FROM insumos
        WHERE LOWER(descricao) = LOWER(?) AND LOWER(fornecedor) = LOWER(?) AND id != ?
    """, (insumo.descricao.strip(), insumo.fornecedor.strip(), insumo_id))
    duplicado = cursor.fetchone()

    if duplicado:
        conn.close()
        raise HTTPException(
            status_code=400,
            detail="Já existe outro insumo com essa descrição e esse fornecedor"
        )

    cursor.execute("""
        UPDATE insumos
        SET descricao = ?, fornecedor = ?, quantidade = ?, cep = ?, rua = ?, bairro = ?, cidade = ?, estado = ?
        WHERE id = ?
    """, (
        insumo.descricao.strip(),
        insumo.fornecedor.strip(),
        insumo.quantidade,
        insumo.cep,
        insumo.rua,
        insumo.bairro,
        insumo.cidade,
        insumo.estado,
        insumo_id
    ))
    conn.commit()

    cursor.execute("SELECT * FROM insumos WHERE id = ?", (insumo_id,))
    atualizado = dict(cursor.fetchone())
    conn.close()
    return atualizado


@app.delete("/insumos/{insumo_id}", tags=["Insumos"])
def deletar_insumo(insumo_id: int):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM insumos WHERE id = ?", (insumo_id,))
    insumo = cursor.fetchone()

    if not insumo:
        conn.close()
        raise HTTPException(status_code=404, detail="Insumo não encontrado")

    cursor.execute("DELETE FROM insumos WHERE id = ?", (insumo_id,))
    conn.commit()
    conn.close()

    return {"mensagem": "Insumo removido com sucesso"}