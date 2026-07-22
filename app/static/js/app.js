// Client-side Application Logic for Concurso Monitor

let currentTab = 'dashboard';
let currentPositionId = null;
let allConcursos = [];
let positionsData = [];

document.addEventListener("DOMContentLoaded", () => {
    loadStats();
    loadCities();
    loadConcursos();
    loadTelegramSettings();
    loadPositions();
});

// Toast notification helper
function showToast(message, type = 'success') {
    const container = document.getElementById('toast-container');
    container.classList.remove('hidden');
    
    const bgColor = type === 'success' ? 'bg-emerald-600/90' : type === 'error' ? 'bg-rose-600/90' : 'bg-sky-600/90';
    const icon = type === 'success' ? 'fa-circle-check' : type === 'error' ? 'fa-circle-exclamation' : 'fa-info-circle';

    container.innerHTML = `
        <div class="${bgColor} text-white px-4 py-3 rounded-xl shadow-lg border border-white/10 flex items-center justify-between">
            <div class="flex items-center gap-3">
                <i class="fa-solid ${icon}"></i>
                <span class="text-sm font-medium">${message}</span>
            </div>
            <button onclick="document.getElementById('toast-container').classList.add('hidden')" class="text-white/80 hover:text-white">
                <i class="fa-solid fa-xmark"></i>
            </button>
        </div>
    `;

    setTimeout(() => {
        container.classList.add('hidden');
    }, 5000);
}

// Tab Switcher
function switchTab(tabName) {
    currentTab = tabName;
    document.querySelectorAll('.tab-btn').forEach(btn => btn.classList.remove('active'));
    document.querySelectorAll('.tab-content').forEach(content => content.classList.add('hidden'));

    document.getElementById(`tab-btn-${tabName}`).classList.add('active');
    document.getElementById(`tab-${tabName}`).classList.remove('hidden');

    if (tabName === 'dashboard') {
        loadStats();
        loadConcursos();
    } else if (tabName === 'studies') {
        loadPositions();
    } else if (tabName === 'telegram') {
        loadTelegramSettings();
    }
}

// Stats Loader
async function loadStats() {
    try {
        const res = await fetch('/api/stats');
        if (res.ok) {
            const data = await res.json();
            document.getElementById('stat-cities').innerText = data.cities_count;
            document.getElementById('stat-concursos').innerText = data.concursos_count;
            document.getElementById('stat-theory').innerText = `${data.avg_theory}%`;
            document.getElementById('stat-accuracy').innerText = `${data.avg_accuracy}%`;
        }
    } catch (e) {
        console.error("Erro ao carregar estatísticas", e);
    }
}

// --- CIDADES DE INTERESSE ---

async function loadCities() {
    try {
        const res = await fetch('/api/cities');
        if (res.ok) {
            const cities = await res.json();
            renderCitiesChips(cities);
        }
    } catch (e) {
        console.error("Erro ao carregar cidades", e);
    }
}

function renderCitiesChips(cities) {
    const container = document.getElementById('cities-list');
    if (!cities || cities.length === 0) {
        container.innerHTML = '<span class="text-xs text-slate-500 p-2">Nenhuma cidade cadastrada ainda...</span>';
        return;
    }

    container.innerHTML = cities.map(c => `
        <span class="inline-flex items-center gap-2 bg-slate-800 border border-slate-700 text-slate-200 px-3 py-1.5 rounded-lg text-xs font-semibold shadow-sm">
            <i class="fa-solid fa-location-dot text-brand-500"></i> ${c.name} (${c.uf})
            <button onclick="handleDeleteCity(${c.id})" class="text-slate-400 hover:text-rose-400 transition-colors ml-1" title="Remover cidade">
                <i class="fa-solid fa-xmark"></i>
            </button>
        </span>
    `).join('');
}

async function handleAddCity(event) {
    event.preventDefault();
    const nameInput = document.getElementById('input-city-name');
    const ufInput = document.getElementById('input-city-uf');

    const name = nameInput.value.trim();
    const uf = ufInput.value.trim().toUpperCase() || 'SP';

    if (!name) return;

    try {
        const res = await fetch('/api/cities', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name, uf })
        });

        if (res.ok) {
            nameInput.value = '';
            showToast(`Cidade ${name} cadastrada com sucesso!`);
            loadCities();
            loadStats();
        } else {
            const err = await res.json();
            showToast(err.detail || 'Erro ao cadastrar cidade.', 'error');
        }
    } catch (e) {
        showToast('Erro de conexão ao adicionar cidade.', 'error');
    }
}

async function handleDeleteCity(cityId) {
    if (!confirm('Deseja remover esta cidade da monitoração?')) return;

    try {
        const res = await fetch(`/api/cities/${cityId}`, { method: 'DELETE' });
        if (res.ok) {
            showToast('Cidade removida.');
            loadCities();
            loadStats();
        } else {
            showToast('Erro ao remover cidade.', 'error');
        }
    } catch (e) {
        showToast('Erro ao excluir cidade.', 'error');
    }
}

// --- CONCURSOS & SCRAPER ---

async function loadConcursos() {
    try {
        const res = await fetch('/api/concursos');
        if (res.ok) {
            allConcursos = await res.json();
            renderConcursosTable(allConcursos);
        }
    } catch (e) {
        console.error("Erro ao carregar concursos", e);
    }
}

function renderConcursosTable(concursos) {
    const tbody = document.getElementById('concursos-tbody');
    if (!concursos || concursos.length === 0) {
        tbody.innerHTML = `
            <tr>
                <td colspan="5" class="py-8 text-center text-slate-500">
                    Nenhum concurso encontrado para as cidades cadastradas.
                </td>
            </tr>
        `;
        return;
    }

    tbody.innerHTML = concursos.map(c => `
        <tr class="hover:bg-slate-800/40 transition-colors">
            <td class="py-4 px-4">
                <div class="font-bold text-white text-base">${c.title}</div>
                <div class="text-xs text-slate-400 mt-0.5">Status: <span class="text-brand-400 font-medium">${c.status}</span></div>
            </td>
            <td class="py-4 px-4">
                <span class="inline-flex items-center gap-1.5 bg-slate-900 text-slate-300 px-2.5 py-1 rounded-md text-xs border border-slate-700">
                    <i class="fa-solid fa-map-pin text-rose-400"></i> ${c.city} / ${c.state}
                </span>
            </td>
            <td class="py-4 px-4">
                <div class="text-xs text-slate-300"><i class="fa-solid fa-user-group text-slate-500 mr-1"></i> ${c.vacancies || 'Não inf.'}</div>
                <div class="text-xs text-emerald-400 font-medium mt-0.5"><i class="fa-solid fa-money-bill-wave text-slate-500 mr-1"></i> ${c.salary || 'Não inf.'}</div>
            </td>
            <td class="py-4 px-4">
                <span class="px-2 py-1 text-[11px] font-semibold bg-purple-500/10 text-purple-400 border border-purple-500/20 rounded-md">
                    ${c.source}
                </span>
            </td>
            <td class="py-4 px-4 text-right">
                <a href="${c.link}" target="_blank" rel="noopener" class="inline-flex items-center gap-1.5 bg-slate-700 hover:bg-brand-600 text-white px-3 py-1.5 rounded-lg text-xs font-medium transition-all shadow">
                    Abrir Edital <i class="fa-solid fa-arrow-up-right-from-square text-[10px]"></i>
                </a>
            </td>
        </tr>
    `).join('');
}

function filterConcursos() {
    const q = document.getElementById('search-concursos').value.toLowerCase();
    const filtered = allConcursos.filter(c => 
        c.title.toLowerCase().includes(q) || c.city.toLowerCase().includes(q)
    );
    renderConcursosTable(filtered);
}

async function triggerScrape() {
    const btn = document.getElementById('btn-trigger-scrape');
    btn.disabled = true;
    btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Varrendo Portais...';

    try {
        const res = await fetch('/api/concursos/scrape', { method: 'POST' });
        if (res.ok) {
            const data = await res.json();
            showToast(`Varredura concluída! ${data.new_concursos} novos concursos encontrados.`);
            loadConcursos();
            loadStats();
        } else {
            showToast('Erro ao realizar raspagem.', 'error');
        }
    } catch (e) {
        showToast('Erro de comunicação ao executar scraper.', 'error');
    } finally {
        btn.disabled = false;
        btn.innerHTML = '<i class="fa-solid fa-bolt"></i> Varrer Concursos Agora';
    }
}

// --- TELEGRAM ---

async function loadTelegramSettings() {
    try {
        const res = await fetch('/api/telegram');
        if (res.ok) {
            const data = await res.json();
            document.getElementById('tg-token').value = data.bot_token || '';
            document.getElementById('tg-chat-id').value = data.chat_id || '';
            document.getElementById('tg-enabled').checked = data.enabled;
        }
    } catch (e) {
        console.error("Erro ao carregar credenciais do Telegram", e);
    }
}

async function handleSaveTelegram(event) {
    event.preventDefault();
    const bot_token = document.getElementById('tg-token').value.trim();
    const chat_id = document.getElementById('tg-chat-id').value.trim();
    const enabled = document.getElementById('tg-enabled').checked;

    try {
        const res = await fetch('/api/telegram', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ bot_token, chat_id, enabled })
        });

        if (res.ok) {
            showToast('Configurações do Telegram salvas com sucesso!');
        } else {
            showToast('Erro ao salvar configurações do Telegram.', 'error');
        }
    } catch (e) {
        showToast('Erro de comunicação ao salvar Telegram.', 'error');
    }
}

async function testTelegramMessage() {
    try {
        const res = await fetch('/api/telegram/test', { method: 'POST' });
        if (res.ok) {
            const data = await res.json();
            showToast(data.message);
        } else {
            const err = await res.json();
            showToast(err.detail || 'Falha ao enviar mensagem de teste.', 'error');
        }
    } catch (e) {
        showToast('Erro ao testar envio no Telegram.', 'error');
    }
}

// --- EDITAL VERTICALIZADO ---

async function loadPositions() {
    try {
        const res = await fetch('/api/positions');
        if (res.ok) {
            positionsData = await res.json();
            renderPositionTabs();
            if (positionsData.length > 0) {
                if (!currentPositionId || !positionsData.find(p => p.id === currentPositionId)) {
                    currentPositionId = positionsData[0].id;
                }
                renderCurrentPosition();
            } else {
                document.getElementById('position-detail').classList.add('hidden');
            }
        }
    } catch (e) {
        console.error("Erro ao carregar edital verticalizado", e);
    }
}

function renderPositionTabs() {
    const container = document.getElementById('position-tabs');
    if (!positionsData || positionsData.length === 0) {
        container.innerHTML = '<span class="text-xs text-slate-500">Nenhum cargo cadastrado. Crie um cargo acima para começar.</span>';
        return;
    }

    container.innerHTML = positionsData.map(p => {
        const activeClass = p.id === currentPositionId ? 'bg-blue-600 text-white font-bold shadow-lg' : 'bg-slate-900 text-slate-400 hover:text-white border border-slate-700';
        return `
            <button onclick="selectPosition(${p.id})" class="px-4 py-2 rounded-xl text-sm transition-all flex items-center gap-2 ${activeClass}">
                <i class="fa-solid fa-briefcase"></i> ${p.name}
            </button>
        `;
    }).join('');
}

function selectPosition(posId) {
    currentPositionId = posId;
    renderPositionTabs();
    renderCurrentPosition();
}

function renderCurrentPosition() {
    const pos = positionsData.find(p => p.id === currentPositionId);
    if (!pos) {
        document.getElementById('position-detail').classList.add('hidden');
        return;
    }

    document.getElementById('position-detail').classList.remove('hidden');
    document.getElementById('current-pos-title').innerText = pos.name;
    document.getElementById('current-pos-exam').innerText = pos.target_exam ? `Concurso: ${pos.target_exam}` : 'Sem concurso específico vinculado';

    renderSubjects(pos.subjects);
}

function renderSubjects(subjects) {
    const container = document.getElementById('subjects-container');
    if (!subjects || subjects.length === 0) {
        container.innerHTML = `
            <div class="bg-slate-800 border border-slate-700/80 rounded-2xl p-8 text-center text-slate-500">
                Nenhuma disciplina cadastrada para este cargo. Clique em "Nova Disciplina" para começar.
            </div>
        `;
        return;
    }

    container.innerHTML = subjects.map(sub => {
        // Calcular progresso da disciplina
        const totalTopics = sub.topics.length;
        const avgTheory = totalTopics > 0 ? roundOneDecimal(sub.topics.reduce((acc, t) => acc + t.theory_percent, 0) / totalTopics) : 0;
        const totalQ = sub.topics.reduce((acc, t) => acc + t.questions_done, 0);
        const totalCorrect = sub.topics.reduce((acc, t) => acc + t.questions_correct, 0);
        const accuracy = totalQ > 0 ? roundOneDecimal((totalCorrect / totalQ) * 100) : 0;

        return `
            <div class="bg-slate-800 border border-slate-700/80 rounded-2xl p-6 shadow-xl space-y-4">
                <!-- Subject Header -->
                <div class="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-slate-700/80 pb-4">
                    <div>
                        <div class="flex items-center gap-3">
                            <h4 class="text-xl font-bold text-white">${sub.name}</h4>
                            <span class="bg-slate-900 text-xs px-2.5 py-1 rounded-md border border-slate-700 text-slate-400 font-mono">Peso: ${sub.weight}</span>
                        </div>
                        <div class="flex items-center gap-4 text-xs text-slate-400 mt-2">
                            <span>Teoria Lida: <strong class="text-purple-400">${avgTheory}%</strong></span>
                            <span>Questões: <strong class="text-slate-200">${totalCorrect}/${totalQ}</strong> (${accuracy}% acertos)</span>
                        </div>
                    </div>

                    <div class="flex items-center gap-2">
                        <button onclick="promptAddTopic(${sub.id})" class="bg-slate-700 hover:bg-slate-600 text-white px-3 py-1.5 rounded-lg text-xs font-medium transition-all">
                            <i class="fa-solid fa-plus"></i> Novo Tópico
                        </button>
                        <button onclick="handleDeleteSubject(${sub.id})" class="text-slate-400 hover:text-rose-400 text-xs p-2">
                            <i class="fa-solid fa-trash"></i>
                        </button>
                    </div>
                </div>

                <!-- Topics Table -->
                <div class="overflow-x-auto">
                    <table class="w-full text-left text-xs text-slate-300">
                        <thead class="bg-slate-900/60 uppercase text-slate-400">
                            <tr>
                                <th class="py-2.5 px-3">Tópico do Edital</th>
                                <th class="py-2.5 px-3 w-44">% Teoria Lida</th>
                                <th class="py-2.5 px-3 w-28 text-center">Revisões</th>
                                <th class="py-2.5 px-3 w-36 text-center">Questões (Acertos/Total)</th>
                                <th class="py-2.5 px-3 w-24 text-center">% Acerto</th>
                                <th class="py-2.5 px-3 text-right">Ação</th>
                            </tr>
                        </thead>
                        <tbody class="divide-y divide-slate-700/40">
                            ${sub.topics.map(t => `
                                <tr>
                                    <td class="py-3 px-3 font-medium text-slate-200">${t.title}</td>
                                    <td class="py-3 px-3">
                                        <div class="flex items-center gap-2">
                                            <input type="range" min="0" max="100" value="${t.theory_percent}" onchange="updateTopicField(${t.id}, 'theory_percent', parseInt(this.value))"
                                                   class="w-full h-1.5 bg-slate-700 rounded-lg appearance-none cursor-pointer accent-purple-500">
                                            <span class="w-8 text-right font-mono text-purple-400 font-bold">${t.theory_percent}%</span>
                                        </div>
                                    </td>
                                    <td class="py-3 px-3 text-center">
                                        <div class="inline-flex items-center gap-1 bg-slate-900 px-2 py-1 rounded-md border border-slate-700">
                                            <button onclick="updateTopicField(${t.id}, 'reviews_count', Math.max(0, ${t.reviews_count} - 1))" class="text-slate-400 hover:text-white px-1">-</button>
                                            <span class="font-mono px-1 font-bold text-amber-400">${t.reviews_count}</span>
                                            <button onclick="updateTopicField(${t.id}, 'reviews_count', ${t.reviews_count} + 1)" class="text-slate-400 hover:text-white px-1">+</button>
                                        </div>
                                    </td>
                                    <td class="py-3 px-3 text-center">
                                        <div class="flex items-center justify-center gap-1">
                                            <input type="number" min="0" value="${t.questions_correct}" onchange="updateTopicField(${t.id}, 'questions_correct', parseInt(this.value))"
                                                   class="w-12 bg-slate-900 border border-slate-700 rounded px-1.5 py-1 text-center font-mono text-emerald-400">
                                            <span>/</span>
                                            <input type="number" min="0" value="${t.questions_done}" onchange="updateTopicField(${t.id}, 'questions_done', parseInt(this.value))"
                                                   class="w-12 bg-slate-900 border border-slate-700 rounded px-1.5 py-1 text-center font-mono text-slate-200">
                                        </div>
                                    </td>
                                    <td class="py-3 px-3 text-center font-mono font-bold ${t.accuracy_percent >= 75 ? 'text-emerald-400' : 'text-amber-400'}">
                                        ${t.accuracy_percent}%
                                    </td>
                                    <td class="py-3 px-3 text-right">
                                        <button onclick="handleDeleteTopic(${t.id})" class="text-slate-400 hover:text-rose-400 p-1">
                                            <i class="fa-solid fa-trash"></i>
                                        </button>
                                    </td>
                                </tr>
                            `).join('')}
                        </tbody>
                    </table>
                </div>
            </div>
        `;
    }).join('');
}

function roundOneDecimal(val) {
    return Math.round(val * 10) / 10;
}

async function handleAddPosition(event) {
    event.preventDefault();
    const name = document.getElementById('input-pos-name').value.trim();
    const target_exam = document.getElementById('input-pos-exam').value.trim();

    if (!name) return;

    try {
        const res = await fetch('/api/positions', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name, target_exam })
        });

        if (res.ok) {
            document.getElementById('input-pos-name').value = '';
            document.getElementById('input-pos-exam').value = '';
            showToast('Cargo criado com sucesso!');
            await loadPositions();
        }
    } catch (e) {
        showToast('Erro ao criar cargo.', 'error');
    }
}

async function handleDeleteCurrentPosition() {
    if (!currentPositionId) return;
    if (!confirm('Deseja excluir este cargo e todo o edital verticalizado associado?')) return;

    try {
        const res = await fetch(`/api/positions/${currentPositionId}`, { method: 'DELETE' });
        if (res.ok) {
            showToast('Cargo excluído.');
            currentPositionId = null;
            await loadPositions();
        }
    } catch (e) {
        showToast('Erro ao excluir cargo.', 'error');
    }
}

function openAddSubjectModal() {
    document.getElementById('modal-subject').classList.remove('hidden');
}

function closeAddSubjectModal() {
    document.getElementById('modal-subject').classList.add('hidden');
}

async function handleAddSubject(event) {
    event.preventDefault();
    const name = document.getElementById('input-sub-name').value.trim();
    const weight = parseFloat(document.getElementById('input-sub-weight').value) || 1.0;

    if (!name || !currentPositionId) return;

    try {
        const res = await fetch(`/api/positions/${currentPositionId}/subjects`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name, weight })
        });

        if (res.ok) {
            closeAddSubjectModal();
            document.getElementById('input-sub-name').value = '';
            showToast('Disciplina cadastrada!');
            await loadPositions();
        }
    } catch (e) {
        showToast('Erro ao cadastrar disciplina.', 'error');
    }
}

async function handleDeleteSubject(subjectId) {
    if (!confirm('Excluir esta disciplina e todos os seus tópicos?')) return;
    try {
        const res = await fetch(`/api/subjects/${subjectId}`, { method: 'DELETE' });
        if (res.ok) {
            showToast('Disciplina excluída.');
            await loadPositions();
        }
    } catch (e) {
        showToast('Erro ao excluir disciplina.', 'error');
    }
}

async function promptAddTopic(subjectId) {
    const title = prompt('Digite o nome do novo tópico do edital:');
    if (!title || !title.trim()) return;

    try {
        const res = await fetch(`/api/subjects/${subjectId}/topics`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ title: title.trim() })
        });

        if (res.ok) {
            showToast('Tópico adicionado!');
            await loadPositions();
            loadStats();
        }
    } catch (e) {
        showToast('Erro ao adicionar tópico.', 'error');
    }
}

async function updateTopicField(topicId, fieldName, value) {
    const payload = {};
    payload[fieldName] = value;

    try {
        const res = await fetch(`/api/topics/${topicId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });

        if (res.ok) {
            await loadPositions();
            loadStats();
        }
    } catch (e) {
        showToast('Erro ao atualizar tópico.', 'error');
    }
}

async function handleDeleteTopic(topicId) {
    if (!confirm('Deseja excluir este tópico do edital?')) return;
    try {
        const res = await fetch(`/api/topics/${topicId}`, { method: 'DELETE' });
        if (res.ok) {
            showToast('Tópico excluído.');
            await loadPositions();
            loadStats();
        }
    } catch (e) {
        showToast('Erro ao excluir tópico.', 'error');
    }
}
