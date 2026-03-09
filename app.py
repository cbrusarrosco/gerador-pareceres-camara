# app.py - VERSÃO APRIMORADA

import os
import re
import fitz
import docx
import sqlite3
import click
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, send_from_directory, flash
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from flask_bcrypt import Bcrypt
import locale
# Esta linha descobre o caminho absoluto para o diretório onde app.py está
basedir = os.path.abspath(os.path.dirname(__file__))
try:
    locale.setlocale(locale.LC_ALL, 'pt_BR.UTF-8')
except locale.Error:
    locale.setlocale(locale.LC_ALL, '')

# --- CONFIGURAÇÃO ---
app = Flask(__name__)

app.secret_key = os.environ.get('SECRET_KEY', 'chave-local-para-nao-quebrar-o-teste')
UPLOAD_FOLDER = os.path.join(basedir, 'uploads')
GENERATED_FOLDER = os.path.join(basedir, 'generated')
TEMPLATE_FOLDER = os.path.join(basedir, 'templates_docx')
DATABASE = os.path.join(basedir, 'database.db')
bcrypt = Bcrypt(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login' 
login_manager.login_message = 'Por favor, faça login para acessar esta página.'
login_manager.login_message_category = 'info'
app.config.update(
    UPLOAD_FOLDER=UPLOAD_FOLDER,
    GENERATED_FOLDER=GENERATED_FOLDER,
    TEMPLATE_FOLDER=TEMPLATE_FOLDER
)
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(GENERATED_FOLDER, exist_ok=True)
os.makedirs(TEMPLATE_FOLDER, exist_ok=True)

# --- BANCO DE DADOS ---
def get_db():
    conn = sqlite3.connect(DATABASE, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

@login_manager.user_loader
def load_user(user_id):
    """Função obrigatória do Flask-Login para carregar o usuário da sessão."""
    db = get_db()
    user_data = db.execute('SELECT * FROM user WHERE id = ?', (user_id,)).fetchone()
    db.close()
    if user_data:
        return User(user_data['id'], user_data['username'], user_data['password_hash'])
    return None

# --- LÓGICA DE SUBSTITUIÇÃO DE TEXTO (para manter a formatação) ---
def replace_text_in_paragraph(paragraph, key, value):
    """
    Substitui um placeholder em um parágrafo, mantendo a formatação.
    Esta versão robusta lida com placeholders quebrados em múltiplos 'runs'.
    """
    if key not in paragraph.text:
        return

    full_text = "".join(run.text for run in paragraph.runs)
    if key not in full_text:
        return

    run_texts = [run.text for run in paragraph.runs]
    found = False
    for i in range(len(run_texts)):
        if key in run_texts[i]:
            run_texts[i] = run_texts[i].replace(key, value)
            found = True
            break
        
        combined_text = "".join(run_texts[i:])
        if combined_text.startswith(key):
            temp_text = ""
            j = i
            while len(temp_text) < len(key) and j < len(run_texts):
                temp_text += run_texts[j]
                j += 1
            
            run_texts[i] = temp_text.replace(key, value, 1)
            for k in range(i + 1, j):
                run_texts[k] = ""
            found = True
            break

    if found:
        for i in range(len(paragraph.runs)):
            paragraph.runs[i].text = run_texts[i]

# --- MODELO DE USUÁRIO PARA O LOGIN ---
class User(UserMixin):
    # UserMixin é uma classe especial do Flask-Login
    # que já nos dá funções como is_authenticated, etc.
    def __init__(self, id, username, password_hash):
        self.id = id
        self.username = username
        self.password_hash = password_hash

    # Esta função é necessária para o Flask-Login
    def get_id(self):
        return str(self.id)

# --- LÓGICA PRINCIPAL ---
def processar_pdf(pdf_path):
    try:
        texto_extraido = ""
        with fitz.open(pdf_path) as doc:
            for page in doc:
                texto_extraido += page.get_text() + " "

        texto_limpo = re.sub(r'\s+', ' ', texto_extraido.replace('\n', ' '))

        print("--- TEXTO LIMPO PARA ANÁLISE REGEX ---")
        print(texto_limpo)
        print("-----------------------------------------")

        dados_do_projeto = {}

        # --- Regex Refinadas (v5) - CORRIGIDAS ---
        
        # Padrão ÚNICO para TIPO e NÚMERO.
        # Procura "PROJETO DE LEI..." e DEPOIS "N... 45"
        padrao_tipo_e_numero = r"(PROJETO DE LEI (ORDIN[ÁA]RIA|COMPLEMENTAR)|PROJETO DE RESOLUÇÃO|PROJETO DE DECRETO LEGISLATIVO|PROPOSTA DE EMENDA [ÁA] LEI ORG[ÂA]NICA MUNICIPAL)\s*(?:N[º'q9]|n[oº9]|ne)\s*(\d+)"
        
        padrao_data = r"(\d{1,2}\s+de\s+\w+\s+(?:de|oe)\s+(\d{4}))"
        padrao_ementa = r"\"\s*(Abre.*?Anual.*?)\s*\""

        print("Iniciando busca por Regex...")

        # Variáveis para combinar o número
        match_numero_val = None
        match_ano_val = None

        if (match := re.search(padrao_tipo_e_numero, texto_limpo, re.IGNORECASE)):
            dados_do_projeto["TIPO_PROJETO"] = match.group(1).upper().strip()
            match_numero_val = match.group(3) # Grupo 3 é o (\d+)
            print(f"SUCESSO (Regex): TIPO_PROJETO={dados_do_projeto['TIPO_PROJETO']}")
            print(f"SUCESSO (Regex): NÚMERO={match_numero_val}")
        else:
            print("FALHA (Regex): Padrão combinado TIPO/NÚMERO não encontrado.")
            
        if (match_data := re.search(padrao_data, texto_limpo, re.IGNORECASE)):
            dados_do_projeto["DATA_PROJETO"] = match_data.group(1).strip()
            match_ano_val = match_data.group(2) # Ex: "2025"
            print(f"SUCESSO (Regex): DATA_PROJETO={dados_do_projeto['DATA_PROJETO']}")
            print(f"SUCESSO (Regex): ANO={match_ano_val}")
        else:
            print("FALHA (Regex): DATA_PROJETO (ex: ...OE 2025) não encontrada.")

        # Combina número e ano no formato que o sistema espera
        if match_numero_val and match_ano_val:
            dados_do_projeto["NUMERO_PROJETO"] = f"{match_numero_val.zfill(3)}/{match_ano_val}" # Formata para "045/2025"
            print(f"SUCESSO (Combinado): NUMERO_PROJETO={dados_do_projeto['NUMERO_PROJETO']}")
        else:
            print("FALHA (Combinado): Não foi possível criar o NUMERO_PROJETO.")

        if (match := re.search(padrao_ementa, texto_limpo, re.IGNORECASE | re.DOTALL)):
            ementa_limpa = match.group(1).strip().replace("Í", "i").replace("çá", "çã").replace("ôe", "õe")
            dados_do_projeto["EMENTA"] = f'"{ementa_limpa}"'
            print(f"SUCESSO (Regex): EMENTA={dados_do_projeto['EMENTA'][:50]}...")
        else:
            print("FALHA (Regex): EMENTA (ex: 'Abre...Anual') não encontrada.")

        print("--- Dados Extraídos ---")
        print(dados_do_projeto)
        print("-----------------------")
        
        return dados_do_projeto

    except Exception as e:
        print(f"Erro ao processar PDF: {e}")
        return {}

def gerar_docx_final(form_data, pdf_filename):
    arquivos_gerados = []
    db = get_db()
    comissoes_selecionadas = form_data.getlist('comissao_selecionada')

    ### --- INÍCIO DA LÓGICA DE NOVOS NOMES --- ###
    tipo_projeto = form_data.get("tipo_projeto", "").upper()
    autoria = form_data.get("autoria", "").upper()
    numero_projeto = form_data.get("numero_projeto", "00-0000")

    prefixo = "DOC" # Um prefixo padrão

    if "PROJETO DE LEI ORDINARIA" in tipo_projeto:
        prefixo = "PLOC" if "CÂMARA" in autoria else "PLOE"
    elif "PROJETO DE LEI COMPLEMENTAR" in tipo_projeto:
        prefixo = "PLCC" if "CÂMARA" in autoria else "PLCE"
    elif "PROJETO DE RESOLUÇÃO" in tipo_projeto:
        prefixo = "PRES"
    elif "PROJETO DE DECRETO LEGISLATIVO" in tipo_projeto:
        prefixo = "PDLC"
    elif "PROPOSTA DE EMENDA" in tipo_projeto:
        prefixo = "PELO"

    # Formata o número (ex: "045/2025" -> "45_2025")
    # Removemos o zero à esquerda para ficar "50_2025" e não "050_2025"
    numero_sem_zero = numero_projeto.split('/')[0].lstrip('0')
    ano = numero_projeto.split('/')[-1]
    numero_formatado = f"{numero_sem_zero}_{ano}"
    ### --- FIM DA LÓGICA DE NOVOS NOMES --- ###

    for sigla in comissoes_selecionadas:
        template_path = os.path.join(app.config['TEMPLATE_FOLDER'], f"template_{sigla.lower()}.docx")

        if not os.path.exists(template_path): 
            print(f"AVISO: Template não encontrado para {sigla} em {template_path}. Pulando...")
            continue

        doc = docx.Document(template_path)
        comissao = db.execute('SELECT * FROM comissoes WHERE sigla = ?', (sigla,)).fetchone()
        membros = db.execute('SELECT * FROM membros WHERE comissao_id = ?', (comissao['id'],)).fetchall()

        relator_id = form_data.get(f'relator_{sigla}')
        if not relator_id:
            print(f"AVISO: Relator não selecionado para {sigla}. Pulando...")
            continue 

        relator = db.execute('SELECT * FROM membros WHERE id = ?', (relator_id,)).fetchone()

        if not relator:
            print(f"AVISO: Relator ID {relator_id} não encontrado no DB para {sigla}. Pulando...")
            continue

        signatarios = [m for m in membros if m['id'] != relator['id']]
        data_parecer = datetime.strptime(form_data.get('data_parecer'), '%Y-%m-%d')

        # (O seu dicionário 'contexto' permanece exatamente o mesmo)
        contexto = {
            "{{TIPO_PROJETO}}": form_data.get("tipo_projeto"),
            "{{NUMERO_PROJETO}}": form_data.get("numero_projeto"),
            "{{DATA_PROJETO}}": form_data.get("data_projeto", "").upper(),
            "{{EMENTA}}": form_data.get("ementa"),
            "{{AUTORIA}}": form_data.get("autoria"),
            "{{DATA_PROTOCOLO}}": datetime.strptime(form_data.get("data_protocolo"), '%Y-%m-%d').strftime('%d/%m/%Y'),
            "{{REGIME_URGENCIA}}": ", EM REGIME DE URGÊNCIA" if 'regime_urgencia' in form_data else "",
            "{{TEXTO_APRESENTACAO}}": f" e apresentada como objeto de deliberação na sessão ordinária do dia {datetime.strptime(form_data.get('data_apresentacao'), '%Y-%m-%d').strftime('%d/%m/%Y')}" if 'incluir_apresentacao' in form_data and form_data.get('data_apresentacao') else ".",
            "{{NUMERO_PARECER}}": form_data.get(f'num_parecer_{sigla}'),
            "{{DATA_PARECER_EXTENSO}}": data_parecer.strftime('%d de %B de %Y').lower(),
            "{{NOME_DA_COMISSAO}}": comissao['nome'].upper(),
            "{{NOME_RELATOR}}": relator['nome'].upper(),
            "{{CARGO_RELATOR}}": relator['cargo'],
            "{{NOME_SIGNATARIO_1}}": signatarios[0]['nome'].upper() if len(signatarios) > 0 else "",
            "{{CARGO_SIGNATARIO_1}}": signatarios[0]['cargo'] if len(signatarios) > 0 else "",
            "{{NOME_SIGNATARIO_2}}": signatarios[1]['nome'].upper() if len(signatarios) > 1 else "",
            "{{CARGO_SIGNATARIO_2}}": signatarios[1]['cargo'] if len(signatarios) > 1 else "",
        }

        for p in doc.paragraphs:
            for key, value in contexto.items():
                replace_text_in_paragraph(p, key, str(value)) 

        for table in doc.tables:
             for row in table.rows:
                for cell in row.cells:
                    for p in cell.paragraphs:
                        for key, value in contexto.items():
                            replace_text_in_paragraph(p, key, str(value))

        ### --- ALTERAÇÃO NO NOME DE SAÍDA --- ###
        nome_saida = f"{prefixo} {numero_formatado} {sigla}.docx"
        caminho_saida = os.path.join(app.config['GENERATED_FOLDER'], nome_saida)
        doc.save(caminho_saida)
        arquivos_gerados.append(nome_saida)
        print(f"SUCESSO: Arquivo '{nome_saida}' gerado.")

        db.execute('INSERT INTO pareceres (pdf_name, docx_name, numero_projeto, data_geracao) VALUES (?, ?, ?, ?)',
                   (pdf_filename, nome_saida, form_data.get('numero_projeto'), datetime.now().strftime("%d/%m/%Y %H:%M:%S")))
        db.commit()

    db.close() 
    return arquivos_gerados

# --- ROTAS ---
@app.route('/', methods=['GET'])
@login_required
def index():
    db = get_db()
    historico = db.execute('SELECT * FROM pareceres ORDER BY id DESC').fetchall()
    return render_template('index.html', historico=historico)

@app.route('/upload', methods=['POST'])
@login_required
def upload():
    file = request.files.get('file')
    if not file or file.filename == '':
        flash('Nenhum arquivo selecionado.')
        return redirect(url_for('index'))
    
    filename = file.filename
    pdf_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    file.save(pdf_path)
    
    dados_pdf = processar_pdf(pdf_path)
    
    db = get_db()
    comissoes = db.execute('SELECT * FROM comissoes').fetchall()
    membros = db.execute('SELECT * FROM membros').fetchall()
    
    return render_template('revisar.html', dados=dados_pdf, comissoes=comissoes, membros=membros, filename=filename)

@app.route('/gerar', methods=['POST'])
@login_required
def gerar():
    # --- NOVO BLOCO DE VERIFICAÇÃO ---
    # Verifica PRIMEIRO se alguma comissão foi selecionada
    comissoes_selecionadas = request.form.getlist('comissao_selecionada')
    if not comissoes_selecionadas:
        flash('Erro: Nenhuma comissão foi selecionada. Tente novamente.')
        # Redirecionar de volta para a página inicial é o mais simples
        return redirect(url_for('index'))
    # --- FIM DO NOVO BLOCO ---

    pdf_filename = request.form.get('pdf_filename')
    
    try:
        arquivos_gerados = gerar_docx_final(request.form, pdf_filename)
        
        # Segunda verificação: Se os arquivos gerados estiverem vazios (ex: erro de template)
        if not arquivos_gerados:
            flash('Erro ao gerar os arquivos. Verifique os templates e dados do formulário.')
            return redirect(url_for('index'))
            
        return render_template('resultado.html', arquivos=arquivos_gerados)

    except Exception as e:
        # Captura erros na geração (ex: template .docx não encontrado)
        print(f"ERRO CRÍTICO EM /gerar: {e}")
        flash(f'Erro interno ao gerar documentos: {e}')
        return redirect(url_for('index'))

# Rotas de download e init-db continuam as mesmas da versão anterior
@app.route('/download/<filename>')
@login_required
def download(filename):
    return send_from_directory(app.config['GENERATED_FOLDER'], filename, as_attachment=True)

@app.route('/deletar_historico/<int:item_id>', methods=['POST'])
@login_required
def deletar_historico(item_id):
    """Deleta um item específico do histórico e seu arquivo."""
    try:
        db = get_db()
        # 1. Pega o nome do arquivo no DB ANTES de deletar
        item = db.execute('SELECT docx_name FROM pareceres WHERE id = ?', (item_id,)).fetchone()

        if item:
            # 2. Deleta o arquivo físico da pasta 'generated'
            arquivo_path = os.path.join(app.config['GENERATED_FOLDER'], item['docx_name'])
            if os.path.exists(arquivo_path):
                os.remove(arquivo_path)

        # 3. Deleta o registro do banco de dados
        db.execute('DELETE FROM pareceres WHERE id = ?', (item_id,))
        db.commit()
        db.close()
        flash('Item do histórico removido com sucesso.', 'success')
    except Exception as e:
        flash(f'Erro ao remover item: {e}', 'danger')
    return redirect(url_for('index'))

@app.route('/limpar_historico', methods=['POST'])
@login_required
def limpar_historico():
    """Deleta TODO o histórico e TODOS os arquivos gerados."""
    try:
        db = get_db()
        # 1. Pega todos os nomes de arquivos no DB
        items = db.execute('SELECT docx_name FROM pareceres').fetchall()

        # 2. Deleta todos os arquivos físicos da pasta 'generated'
        for item in items:
            arquivo_path = os.path.join(app.config['GENERATED_FOLDER'], item['docx_name'])
            if os.path.exists(arquivo_path):
                os.remove(arquivo_path)

        # 3. Deleta todos os registros do banco de dados
        db.execute('DELETE FROM pareceres')
        db.commit()
        db.close()
        flash('Histórico completo removido com sucesso.', 'success')
    except Exception as e:
        flash(f'Erro ao limpar histórico: {e}', 'danger')
    return redirect(url_for('index'))

@app.route('/adicionar_membro', methods=['POST'])
@login_required
def adicionar_membro():
    try:
        nome = request.form['nome']
        cargo = request.form['cargo']
        comissao_id = request.form['comissao_id']
        
        db = get_db()
        db.execute('INSERT INTO membros (nome, cargo, comissao_id) VALUES (?, ?, ?)',
                   (nome, cargo, comissao_id))
        db.commit()
        db.close()
        flash(f'Membro "{nome}" adicionado com sucesso!')
    except Exception as e:
        flash(f'Erro ao adicionar membro: {e}')
    return redirect(url_for('gerenciar'))

@app.route('/deletar_membro', methods=['POST'])
@login_required
def deletar_membro():
    try:
        membro_id = request.form['membro_id']
        
        db = get_db()
        # Pega o nome para a mensagem flash ANTES de deletar
        nome_membro = db.execute('SELECT nome FROM membros WHERE id = ?', (membro_id,)).fetchone()['nome']
        
        db.execute('DELETE FROM membros WHERE id = ?', (membro_id,))
        db.commit()
        db.close()
        flash(f'Membro "{nome_membro}" removido com sucesso!')
    except Exception as e:
        flash(f'Erro ao remover membro: {e}')
    return redirect(url_for('gerenciar'))

@app.route('/editar_membro/<int:membro_id>', methods=['GET'])
@login_required
def editar_membro(membro_id):
    """Exibe o formulário de edição para um membro específico."""
    db = get_db()
    membro = db.execute('SELECT * FROM membros WHERE id = ?', (membro_id,)).fetchone()
    comissoes = db.execute('SELECT * FROM comissoes ORDER BY nome').fetchall()
    db.close()
    
    if membro is None:
        flash('Membro não encontrado.')
        return redirect(url_for('gerenciar'))
        
    return render_template('editar_membro.html', membro=membro, comissoes=comissoes)

@app.route('/atualizar_membro', methods=['POST'])
@login_required
def atualizar_membro():
    """Processa a atualização dos dados do membro."""
    try:
        membro_id = request.form['membro_id']
        nome = request.form['nome']
        cargo = request.form['cargo']
        comissao_id = request.form['comissao_id']
        
        db = get_db()
        db.execute('UPDATE membros SET nome = ?, cargo = ?, comissao_id = ? WHERE id = ?',
                   (nome, cargo, comissao_id, membro_id))
        db.commit()
        db.close()
        flash(f'Dados do membro "{nome}" atualizados com sucesso!')
    except Exception as e:
        flash(f'Erro ao atualizar membro: {e}')
        
    return redirect(url_for('gerenciar'))

@app.route('/gerenciar')
@login_required
def gerenciar():
    db = get_db()
    comissoes = db.execute('SELECT * FROM comissoes ORDER BY nome').fetchall()
    
    # Vamos buscar os membros e agrupá-los por comissão
    membros_por_comissao = {}
    for comissao in comissoes:
        membros = db.execute(
            'SELECT * FROM membros WHERE comissao_id = ? ORDER BY nome', 
            (comissao['id'],)
        ).fetchall()
        membros_por_comissao[comissao['id']] = membros
    
    db.close()
    return render_template(
        'gerenciar.html', 
        comissoes=comissoes, 
        membros_por_comissao=membros_por_comissao
    )

@app.cli.command('create-admin')
@click.argument('username')
@click.argument('password')
def create_admin_command(username, password):
    """Cria um novo usuário administrador."""
    db = get_db()
    try:
        # Criptografa a senha
        hashed_password = bcrypt.generate_password_hash(password).decode('utf-8')
        db.execute('INSERT INTO user (username, password_hash) VALUES (?, ?)',
                   (username, hashed_password))
        db.commit()
        print(f"Administrador '{username}' criado com sucesso.")
    except sqlite3.IntegrityError:
        print(f"Erro: Usuário '{username}' já existe.")
    except Exception as e:
        print(f"Erro ao criar administrador: {e}")
    finally:
        db.close()

@app.cli.command('init-db')
def init_db_command():
    """Limpa os dados existentes e cria novas tabelas com dados padrão."""
    db = get_db()

    print("Limpando tabelas antigas (se existiam)...")

    db.execute("DROP TABLE IF EXISTS pareceres;")
    db.execute("DROP TABLE IF EXISTS membros;")
    db.execute("DROP TABLE IF EXISTS comissoes;")
    db.execute("DROP TABLE IF EXISTS user;")

    print("Criando novas tabelas...")

    db.execute('''
    CREATE TABLE comissoes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nome TEXT NOT NULL,
        sigla TEXT NOT NULL UNIQUE
    );
    ''')

    db.execute('''
    CREATE TABLE membros (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        comissao_id INTEGER NOT NULL,
        nome TEXT NOT NULL,
        cargo TEXT NOT NULL,
        FOREIGN KEY (comissao_id) REFERENCES comissoes (id)
    );
    ''')

    db.execute('''
    CREATE TABLE pareceres (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        pdf_name TEXT NOT NULL,
        docx_name TEXT NOT NULL,
        numero_projeto TEXT,
        data_geracao TEXT NOT NULL
    );
    ''')

    db.execute('''
    CREATE TABLE user (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT NOT NULL UNIQUE,
        password_hash TEXT NOT NULL
    );
    ''')

    print("Tabelas (comissoes, membros, pareceres, user) criadas.")

    # Inserir Comissões Padrão
    comissoes = [
        ('Comissão de Justiça e Redação', 'CJR'),
        ('Comissão de Finanças e Orçamento', 'CFO'),
        ('Comissão de Obras, Serviços Públicos e Atividades Privadas', 'COSPAP'),
        ('Comissão de Educação, Saúde e Assistência Social', 'CESAS')
    ]

    db.executemany(
        'INSERT INTO comissoes (nome, sigla) VALUES (?, ?)',
        comissoes
    )

    print("Comissões padrão inseridas.")

    db.commit()

    # Buscar IDs das comissões
    try:
        cjr_id = db.execute(
            "SELECT id FROM comissoes WHERE sigla = 'CJR'"
        ).fetchone()['id']

        cfo_id = db.execute(
            "SELECT id FROM comissoes WHERE sigla = 'CFO'"
        ).fetchone()['id']

        cospap_id = db.execute(
            "SELECT id FROM comissoes WHERE sigla = 'COSPAP'"
        ).fetchone()['id']

        cesas_id = db.execute(
            "SELECT id FROM comissoes WHERE sigla = 'CESAS'"
        ).fetchone()['id']

    except TypeError:
        print("ERRO: Falha ao buscar IDs das comissões. Verifique as siglas.")
        db.close()
        return

    # Inserir Membros Padrão
    membros = [
        (cjr_id, 'Vereador A (CJR)', 'Presidente'),
        (cjr_id, 'Vereador B (CJR)', 'Vice-Presidente'),
        (cjr_id, 'Vereador C (CJR)', 'Membro'),

        (cfo_id, 'Vereador D (CFO)', 'Presidente'),
        (cfo_id, 'Vereador E (CFO)', 'Vice-Presidente'),
        (cfo_id, 'Vereador F (CFO)', 'Membro'),

        (cospap_id, 'Vereador G (COSPAP)', 'Presidente'),
        (cospap_id, 'Vereador H (COSPAP)', 'Vice-Presidente'),
        (cospap_id, 'Vereador I (COSPAP)', 'Membro'),

        (cesas_id, 'Vereador J (CESAS)', 'Presidente'),
        (cesas_id, 'Vereador K (CESAS)', 'Vice-Presidente'),
        (cesas_id, 'Vereador L (CESAS)', 'Membro')
    ]

    db.executemany(
        'INSERT INTO membros (comissao_id, nome, cargo) VALUES (?, ?, ?)',
        membros
    )

    print("Membros padrão inseridos.")

    # Criar usuário admin
    print("Criando usuário administrador padrão...")

    senha_admin = bcrypt.generate_password_hash("admin123").decode("utf-8")

    db.execute(
        "INSERT OR IGNORE INTO user (username, password_hash) VALUES (?, ?)",
        ("admin", senha_admin)
    )

    db.commit()
    db.close()

    print("Banco de dados inicializado com sucesso.")

@app.route('/login', methods=['GET', 'POST'])
def login():
    # Se o usuário já estiver logado, redireciona para a home
    if current_user.is_authenticated:
        return redirect(url_for('index'))
        
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        
        db = get_db()
        user_data = db.execute('SELECT * FROM user WHERE username = ?', (username,)).fetchone()
        db.close()
        
        # Verifica se o usuário existe e se a senha está correta
        if user_data:
            user = User(user_data['id'], user_data['username'], user_data['password_hash'])
            if bcrypt.check_password_hash(user.password_hash, password):
                login_user(user) # <-- A "mágica" do Flask-Login acontece aqui
                flash('Login realizado com sucesso!', 'success')
                return redirect(url_for('index'))
                
        flash('Usuário ou senha inválidos.', 'danger')
        
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Você foi desconectado.', 'success')
    return redirect(url_for('login'))


# Inicializa banco automaticamente no deploy
def init_db_if_needed():
    with app.app_context():
        db = get_db()

        tables = db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()

        table_names = {t['name'] for t in tables}

        required_tables = {"user", "comissoes", "membros", "pareceres"}

        if not required_tables.issubset(table_names):
            print("Estrutura do banco incompleta. Recriando banco...")
            init_db_command()

        db.close()

init_db_if_needed()