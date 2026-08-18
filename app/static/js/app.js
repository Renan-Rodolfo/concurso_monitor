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
    } else if (tabName === 'jobsearch') {
        loadCandidateProfile();
        loadJobQueries();
        loadJobOpportunities();
        loadSmartTerms();
    } else if (tabName === 'finances') {
        loadFinanceData();
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

// --- JOB SEARCH & CANDIDATE HUB ---

let currentJobSubTab = 'profile';
let allJobs = [];

function switchJobSubTab(subTabName) {
    currentJobSubTab = subTabName;
    document.querySelectorAll('.job-subtab-content').forEach(c => c.classList.add('hidden'));
    
    ['profile', 'queries', 'board'].forEach(name => {
        const btn = document.getElementById(`job-subtab-btn-${name}`);
        if (btn) {
            if (name === subTabName) {
                btn.className = 'px-3.5 py-1.5 text-xs font-semibold rounded-lg transition-all text-white bg-slate-800 border border-slate-700 shadow';
            } else {
                btn.className = 'px-3.5 py-1.5 text-xs font-semibold rounded-lg transition-all text-slate-400 hover:text-white';
            }
        }
    });

    const target = document.getElementById(`job-subtab-${subTabName}`);
    if (target) target.classList.remove('hidden');

    if (subTabName === 'profile') loadCandidateProfile();
    else if (subTabName === 'queries') loadSmartTerms();
    else if (subTabName === 'board') loadJobOpportunities();
}

async function loadCandidateProfile() {
    try {
        const res = await fetch('/api/job-search/profile');
        if (res.ok) {
            const p = await res.json();
            document.getElementById('job-prof-name').value = p.full_name || '';
            document.getElementById('job-prof-headline').value = p.headline || '';
            document.getElementById('job-prof-location').value = p.location || '';
            document.getElementById('job-prof-primary-skills').value = p.primary_skills || '';
            document.getElementById('job-prof-secondary-skills').value = p.secondary_skills || '';
            document.getElementById('job-prof-target-roles').value = p.target_roles || '';
            document.getElementById('job-prof-dealbreakers').value = p.dealbreakers || '';
            document.getElementById('job-prof-summary').value = p.experience_summary || '';
        }
    } catch (e) {
        console.error("Erro ao carregar perfil do candidato", e);
    }
}

async function handleSaveCandidateProfile(event) {
    event.preventDefault();
    const payload = {
        full_name: document.getElementById('job-prof-name').value.trim(),
        headline: document.getElementById('job-prof-headline').value.trim(),
        location: document.getElementById('job-prof-location').value.trim(),
        primary_skills: document.getElementById('job-prof-primary-skills').value.trim(),
        secondary_skills: document.getElementById('job-prof-secondary-skills').value.trim(),
        target_roles: document.getElementById('job-prof-target-roles').value.trim(),
        dealbreakers: document.getElementById('job-prof-dealbreakers').value.trim(),
        experience_summary: document.getElementById('job-prof-summary').value.trim(),
    };

    try {
        const res = await fetch('/api/job-search/profile', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });

        if (res.ok) {
            showToast('Perfil do candidato salvo com sucesso!');
            loadSmartTerms();
        } else {
            showToast('Erro ao salvar perfil.', 'error');
        }
    } catch (e) {
        showToast('Erro de conexão ao salvar perfil.', 'error');
    }
}

async function loadJobQueries() {
    try {
        const res = await fetch('/api/job-search/queries');
        if (res.ok) {
            const queries = await res.json();
            renderJobQueriesList(queries);
        }
    } catch (e) {
        console.error("Erro ao carregar parâmetros de busca", e);
    }
}

function renderJobQueriesList(queries) {
    const container = document.getElementById('job-queries-list');
    if (!queries || queries.length === 0) {
        container.innerHTML = '<span class="text-xs text-slate-500 col-span-3">Nenhum filtro de busca cadastrado ainda.</span>';
        return;
    }

    container.innerHTML = queries.map(q => `
        <div class="bg-slate-900 border border-slate-700/80 rounded-xl p-4 flex items-center justify-between shadow-sm">
            <div>
                <div class="font-bold text-white text-sm">${q.role_title}</div>
                <div class="text-xs text-slate-400 mt-1 flex items-center gap-2">
                    <span><i class="fa-solid fa-location-dot text-rose-400 mr-1"></i>${q.location}</span>
                    <span class="bg-slate-800 text-slate-300 px-2 py-0.5 rounded text-[11px] font-mono border border-slate-700">${q.work_model}</span>
                </div>
            </div>
            <button onclick="handleDeleteJobQuery(${q.id})" class="text-slate-400 hover:text-rose-400 p-2" title="Excluir filtro">
                <i class="fa-solid fa-trash"></i>
            </button>
        </div>
    `).join('');
}

async function handleAddJobQuery(event) {
    event.preventDefault();
    const role_title = document.getElementById('input-query-title').value.trim();
    const location = document.getElementById('input-query-location').value.trim() || 'Remoto';
    const work_model = document.getElementById('input-query-model').value;

    if (!role_title) return;

    try {
        const res = await fetch('/api/job-search/queries', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ role_title, location, work_model })
        });

        if (res.ok) {
            document.getElementById('input-query-title').value = '';
            showToast('Filtro de busca adicionado!');
            loadJobQueries();
        } else {
            showToast('Erro ao adicionar filtro.', 'error');
        }
    } catch (e) {
        showToast('Erro de conexão ao adicionar filtro.', 'error');
    }
}

async function handleDeleteJobQuery(queryId) {
    if (!confirm('Deseja excluir este filtro de busca?')) return;
    try {
        const res = await fetch(`/api/job-search/queries/${queryId}`, { method: 'DELETE' });
        if (res.ok) {
            showToast('Filtro excluído.');
            loadJobQueries();
        }
    } catch (e) {
        showToast('Erro ao excluir filtro.', 'error');
    }
}

async function loadJobOpportunities() {
    const statusSelect = document.getElementById('filter-job-status');
    const status = statusSelect ? statusSelect.value : 'Todas';
    try {
        const res = await fetch(`/api/job-search/jobs?status=${encodeURIComponent(status)}`);
        if (res.ok) {
            allJobs = await res.json();
            renderJobsTable(allJobs);
        }
    } catch (e) {
        console.error("Erro ao carregar oportunidades de vagas", e);
    }
}

function renderJobsTable(jobs) {
    const tbody = document.getElementById('jobs-tbody');
    if (!jobs || jobs.length === 0) {
        tbody.innerHTML = `
            <tr>
                <td colspan="6" class="py-8 text-center text-slate-500">
                    Nenhuma vaga encontrada para este filtro.
                </td>
            </tr>
        `;
        return;
    }

    tbody.innerHTML = jobs.map(j => {
        const fitColor = j.fit_score >= 70 ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20' :
                         j.fit_score >= 40 ? 'bg-amber-500/10 text-amber-400 border-amber-500/20' :
                         'bg-slate-500/10 text-slate-400 border-slate-500/20';

        return `
            <tr class="hover:bg-slate-800/40 transition-colors">
                <td class="py-4 px-4">
                    <div class="font-bold text-white text-base">${j.title}</div>
                    <div class="text-xs text-slate-400 mt-0.5"><i class="fa-solid fa-building text-slate-500 mr-1"></i>${j.company}</div>
                </td>
                <td class="py-4 px-4">
                    <div class="text-xs text-slate-300"><i class="fa-solid fa-location-dot text-rose-400 mr-1"></i>${j.location}</div>
                    <span class="inline-block mt-1 px-2 py-0.5 text-[10px] font-mono bg-slate-900 text-slate-400 rounded border border-slate-700">${j.work_model}</span>
                </td>
                <td class="py-4 px-4">
                    <div class="text-xs text-emerald-400 font-medium">${j.salary || 'Não informado'}</div>
                    <div class="text-[11px] text-slate-400 mt-0.5 truncate max-w-xs" title="${j.skills_required || ''}">${j.skills_required || 'Sem requisitos especificados'}</div>
                </td>
                <td class="py-4 px-4 text-center">
                    <span class="inline-flex items-center px-2.5 py-1 rounded-full text-xs font-bold font-mono border ${fitColor}">
                        ${j.fit_score}% Fit
                    </span>
                </td>
                <td class="py-4 px-4 text-center">
                    <select onchange="handleUpdateJobStatus(${j.id}, this.value)" class="bg-slate-900 border border-slate-700 rounded-lg px-2.5 py-1 text-xs text-white focus:outline-none focus:border-purple-500 font-medium">
                        <option value="Nova" ${j.status === 'Nova' ? 'selected' : ''}>Nova</option>
                        <option value="CV Gerado" ${j.status === 'CV Gerado' ? 'selected' : ''}>CV Gerado</option>
                        <option value="Aplicado" ${j.status === 'Aplicado' ? 'selected' : ''}>Aplicado</option>
                        <option value="Entrevista" ${j.status === 'Entrevista' ? 'selected' : ''}>Entrevista</option>
                        <option value="Aprovado" ${j.status === 'Aprovado' ? 'selected' : ''}>Aprovado</option>
                        <option value="Descartado" ${j.status === 'Descartado' ? 'selected' : ''}>Descartado</option>
                    </select>
                </td>
                <td class="py-4 px-4 text-right">
                    <div class="flex items-center justify-end gap-2">
                        ${j.link ? `<a href="${j.link}" target="_blank" rel="noopener" class="text-slate-400 hover:text-emerald-400 p-1.5"><i class="fa-solid fa-arrow-up-right-from-square"></i></a>` : ''}
                        <button onclick="handleDeleteJob(${j.id})" class="text-slate-400 hover:text-rose-400 p-1.5"><i class="fa-solid fa-trash"></i></button>
                    </div>
                </td>
            </tr>
        `;
    }).join('');
}

function openAddJobModal() {
    document.getElementById('modal-job').classList.remove('hidden');
}

function closeAddJobModal() {
    document.getElementById('modal-job').classList.add('hidden');
}

async function handleAddJob(event) {
    event.preventDefault();
    const title = document.getElementById('input-job-title').value.trim();
    const company = document.getElementById('input-job-company').value.trim();
    const location = document.getElementById('input-job-location').value.trim() || 'Remoto';
    const work_model = document.getElementById('input-job-model').value;
    const salary = document.getElementById('input-job-salary').value.trim();
    const link = document.getElementById('input-job-link').value.trim();
    const skills_required = document.getElementById('input-job-skills').value.trim();
    const notes = document.getElementById('input-job-notes').value.trim();

    if (!title || !company) return;

    try {
        const res = await fetch('/api/job-search/jobs', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ title, company, location, work_model, salary, link, skills_required, notes })
        });

        if (res.ok) {
            closeAddJobModal();
            document.getElementById('input-job-title').value = '';
            document.getElementById('input-job-company').value = '';
            document.getElementById('input-job-link').value = '';
            document.getElementById('input-job-skills').value = '';
            document.getElementById('input-job-notes').value = '';
            showToast('Oportunidade cadastrada com sucesso!');
            loadJobOpportunities();
        } else {
            showToast('Erro ao cadastrar vaga.', 'error');
        }
    } catch (e) {
        showToast('Erro de conexão ao salvar vaga.', 'error');
    }
}

async function handleUpdateJobStatus(jobId, newStatus) {
    try {
        const res = await fetch(`/api/job-search/jobs/${jobId}/status`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ status: newStatus })
        });

        if (res.ok) {
            showToast(`Status da vaga atualizado para "${newStatus}"!`);
            loadJobOpportunities();
        } else {
            showToast('Erro ao atualizar status.', 'error');
        }
    } catch (e) {
        showToast('Erro ao atualizar vaga.', 'error');
    }
}

async function handleDeleteJob(jobId) {
    if (!confirm('Deseja excluir esta vaga do painel?')) return;
    try {
        const res = await fetch(`/api/job-search/jobs/${jobId}`, { method: 'DELETE' });
        if (res.ok) {
            showToast('Vaga excluída.');
            loadJobOpportunities();
        }
    } catch (e) {
        showToast('Erro ao excluir vaga.', 'error');
    }
}

// ============================================================
// LIVE JOB SEARCH
// ============================================================

let liveSearchResults = [];

async function runLiveJobSearch() {
    const btn = document.getElementById('btn-search-live');
    const loader = document.getElementById('live-search-loader');
    const errorBox = document.getElementById('live-search-error');
    const idle = document.getElementById('live-search-idle');
    const summary = document.getElementById('live-search-summary');
    const resultsGrid = document.getElementById('live-search-results');

    // Coletar filtros do painel
    const countryRaw = (document.getElementById('live-filter-country')?.value || '').trim();
    const workMode = (document.getElementById('live-filter-workmode')?.value || '').trim() || null;
    const jobageRaw = (document.getElementById('live-filter-jobage')?.value || '').trim();

    // Separar país de região (valores prefixados com __)
    let country = null;
    let region = null;
    if (countryRaw.startsWith('__')) {
        region = countryRaw.replace('__', '');  // ex: "__latam" → "latam"
    } else if (countryRaw) {
        country = countryRaw;                    // ex: "br"
    }

    const searchBody = {
        country: country,
        region: region,
        work_mode: workMode || null,
        jobage: jobageRaw ? parseInt(jobageRaw) : null,
        limit: 25
    };

    // Reset state
    btn.disabled = true;
    btn.innerHTML = '<i class="fa-solid fa-circle-notch fa-spin"></i> Buscando...';
    loader.classList.remove('hidden');
    errorBox.classList.add('hidden');
    idle.classList.add('hidden');
    summary.classList.add('hidden');
    resultsGrid.classList.add('hidden');
    resultsGrid.innerHTML = '';

    try {
        const res = await fetch('/api/job-search/search-live', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(searchBody)
        });
        const data = await res.json();

        loader.classList.add('hidden');

        if (!res.ok) {
            document.getElementById('live-search-error-msg').textContent = data.detail || 'Erro inesperado ao buscar vagas.';
            errorBox.classList.remove('hidden');
            return;
        }

        liveSearchResults = data.results || [];

        if (liveSearchResults.length === 0) {
            const countryLabel = country ? `país "${country.toUpperCase()}"` : region ? `região "${region}"` : 'filtros selecionados';
            document.getElementById('live-search-error-msg').textContent =
                `Nenhuma vaga encontrada para ${countryLabel}. Tente ampliar os filtros (ex: remova o filtro de país ou modalidade).`;
            errorBox.classList.remove('hidden');
            return;
        }

        // Show summary bar
        const countryBadge = country ? ` · ${country.toUpperCase()}` : region ? ` · ${region.toUpperCase()}` : ' · Global';
        document.getElementById('live-results-count').textContent = liveSearchResults.length;
        const now = new Date();
        document.getElementById('live-search-timestamp').textContent =
            `${now.toLocaleTimeString('pt-BR')}${countryBadge}`;

        summary.classList.remove('hidden');
        resultsGrid.classList.remove('hidden');
        renderLiveResults(liveSearchResults);

    } catch (e) {
        loader.classList.add('hidden');
        document.getElementById('live-search-error-msg').textContent =
            'Falha na conexão com o servidor. Verifique sua conexão e tente novamente.';
        errorBox.classList.remove('hidden');
        console.error('Live search error:', e);
    } finally {
        btn.disabled = false;
        btn.innerHTML = '<i class="fa-solid fa-magnifying-glass-chart"></i> Buscar Vagas';
    }
}


function sortLiveResults() {
    const sortBy = document.getElementById('live-sort-select').value;
    const sorted = [...liveSearchResults];
    if (sortBy === 'fit') {
        sorted.sort((a, b) => b.fit_score - a.fit_score);
    } else if (sortBy === 'title') {
        sorted.sort((a, b) => a.title.localeCompare(b.title));
    } else if (sortBy === 'company') {
        sorted.sort((a, b) => a.company.localeCompare(b.company));
    }
    renderLiveResults(sorted);
}

function fitScoreBadgeClass(score) {
    if (score >= 80) return 'bg-emerald-900/60 text-emerald-300 border-emerald-700/50';
    if (score >= 55) return 'bg-sky-900/60 text-sky-300 border-sky-700/50';
    if (score >= 30) return 'bg-yellow-900/60 text-yellow-300 border-yellow-700/50';
    return 'bg-slate-700/60 text-slate-400 border-slate-600/50';
}

function fitScoreBarColor(score) {
    if (score >= 80) return 'bg-emerald-500';
    if (score >= 55) return 'bg-sky-500';
    if (score >= 30) return 'bg-yellow-500';
    return 'bg-slate-500';
}

function seniorityLabel(s) {
    const map = { junior: 'Júnior', middle: 'Pleno', senior: 'Sênior', lead: 'Lead', staff: 'Staff', principal: 'Principal' };
    return map[s] || s;
}

function renderLiveResults(results) {
    const grid = document.getElementById('live-search-results');
    grid.innerHTML = results.map((job, idx) => {
        const score = job.fit_score || 0;
        const badgeClass = fitScoreBadgeClass(score);
        const barColor = fitScoreBarColor(score);
        const skills = (job.skills_required || '').split(',').filter(s => s.trim()).slice(0, 5);
        const postedDate = job.posted_at ? new Date(job.posted_at).toLocaleDateString('pt-BR') : '';
        const seniority = job.seniority ? `<span class="text-xs bg-indigo-900/50 text-indigo-300 border border-indigo-700/40 px-2 py-0.5 rounded-full">${seniorityLabel(job.seniority)}</span>` : '';

        return `
        <div class="bg-slate-900/70 border border-slate-700/60 rounded-2xl p-4 flex flex-col gap-3 hover:border-sky-700/60 hover:shadow-lg hover:shadow-sky-900/20 transition-all group" data-idx="${idx}">
            <!-- Header: Fit + source -->
            <div class="flex items-start justify-between gap-2">
                <div class="flex-1 min-w-0">
                    <p class="font-semibold text-white text-sm leading-tight line-clamp-2 group-hover:text-sky-300 transition-colors">${job.title}</p>
                    <p class="text-slate-400 text-xs mt-0.5 truncate">${job.company}</p>
                </div>
                <span class="border text-xs font-bold px-2.5 py-1 rounded-xl whitespace-nowrap flex-shrink-0 ${badgeClass}">
                    ${score.toFixed(0)}% fit
                </span>
            </div>

            <!-- Fit bar -->
            <div class="w-full bg-slate-800 rounded-full h-1.5 overflow-hidden">
                <div class="${barColor} h-1.5 rounded-full transition-all" style="width: ${score}%"></div>
            </div>

            <!-- Meta row -->
            <div class="flex flex-wrap items-center gap-1.5 text-xs text-slate-500">
                <span><i class="fa-solid fa-location-dot mr-1 text-slate-600"></i>${job.location || 'N/A'}</span>
                <span class="text-slate-700">·</span>
                <span class="capitalize">${job.work_model || 'Remoto'}</span>
                ${job.salary ? `<span class="text-slate-700">·</span><span class="text-emerald-400">${job.salary}</span>` : ''}
                ${postedDate ? `<span class="text-slate-700">·</span><span>${postedDate}</span>` : ''}
            </div>

            <!-- Seniority + search tag -->
            <div class="flex flex-wrap items-center gap-1.5">
                ${seniority}
                <span class="text-xs bg-slate-800 text-slate-500 border border-slate-700 px-2 py-0.5 rounded-full truncate max-w-full">
                    <i class="fa-solid fa-magnifying-glass mr-1"></i>${job.query_used || ''}
                </span>
            </div>

            <!-- Skills tags -->
            ${skills.length > 0 ? `
            <div class="flex flex-wrap gap-1.5">
                ${skills.map(s => `<span class="text-xs bg-slate-800 border border-slate-700/50 text-sky-400 px-2 py-0.5 rounded-lg">${s.trim()}</span>`).join('')}
            </div>` : ''}

            <!-- Description preview -->
            ${job.description ? `<p class="text-xs text-slate-500 line-clamp-2 leading-relaxed">${job.description}</p>` : ''}

            <!-- Actions -->
            <div class="flex gap-2 pt-1 border-t border-slate-800 mt-auto">
                <a href="${job.link}" target="_blank" rel="noopener noreferrer"
                   class="flex-1 text-center bg-slate-800 hover:bg-slate-700 text-slate-300 hover:text-white text-xs font-medium py-2 rounded-xl transition-all border border-slate-700/50 flex items-center justify-center gap-1.5">
                    <i class="fa-solid fa-arrow-up-right-from-square"></i> Ver Vaga
                </a>
                <button onclick="saveJobFromSearch(${idx})"
                        id="save-btn-${idx}"
                        class="flex-1 bg-sky-700 hover:bg-sky-600 text-white text-xs font-semibold py-2 rounded-xl transition-all flex items-center justify-center gap-1.5 shadow-sm shadow-sky-900/40">
                    <i class="fa-solid fa-bookmark"></i> Salvar no Board
                </button>
            </div>
        </div>`;
    }).join('');
}

async function saveJobFromSearch(idx) {
    const job = liveSearchResults[idx];
    if (!job) return;

    const btn = document.getElementById(`save-btn-${idx}`);
    if (btn) {
        btn.disabled = true;
        btn.innerHTML = '<i class="fa-solid fa-circle-notch fa-spin"></i> Salvando...';
    }

    try {
        const res = await fetch('/api/job-search/jobs/save-from-search', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                title: job.title,
                company: job.company,
                location: job.location,
                work_model: job.work_model,
                salary: job.salary || '',
                link: job.link,
                description: job.description,
                skills_required: job.skills_required,
                notes: `Encontrada via Busca ao Vivo (freehire.dev) — filtro: "${job.query_used}"`
            })
        });

        if (res.ok) {
            if (btn) {
                btn.innerHTML = '<i class="fa-solid fa-circle-check"></i> Salva!';
                btn.classList.remove('bg-sky-700', 'hover:bg-sky-600');
                btn.classList.add('bg-emerald-800', 'cursor-default');
            }
            showToast(`"${job.title}" salva no Board de Candidaturas!`);
            loadJobOpportunities();
        } else {
            const err = await res.json();
            if (btn) {
                btn.disabled = false;
                btn.innerHTML = '<i class="fa-solid fa-bookmark"></i> Salvar no Board';
            }
            if (res.status === 400 && err.detail && err.detail.includes('já salva')) {
                showToast('Esta vaga já está no seu Board!', 'info');
                if (btn) {
                    btn.innerHTML = '<i class="fa-solid fa-circle-check"></i> Já no Board';
                    btn.classList.remove('bg-sky-700', 'hover:bg-sky-600');
                    btn.classList.add('bg-slate-700', 'cursor-default');
                    btn.disabled = true;
                }
            } else {
                showToast('Erro ao salvar vaga no Board.', 'error');
            }
        }
    } catch (e) {
        if (btn) {
            btn.disabled = false;
            btn.innerHTML = '<i class="fa-solid fa-bookmark"></i> Salvar no Board';
        }
                if (btn) {
                    btn.disabled = false;
                    btn.innerHTML = '<i class="fa-solid fa-bookmark"></i> Salvar no Board';
                }
                showToast('Erro de conexão ao salvar vaga.', 'error');
                console.error('Save from search error:', e);
            }
}

// =========================================================
// SMART JOB SEARCH — Busca Inteligente Multi-fonte
// =========================================================

let smartSearchResults = [];

const SOURCE_CONFIG = {
    'LinkedIn': {
        color: 'bg-blue-900/60 border-blue-700/50 text-blue-300',
        icon: 'fa-brands fa-linkedin',
        dot: 'bg-blue-400',
    },
    'Gupy': {
        color: 'bg-orange-900/50 border-orange-700/50 text-orange-300',
        icon: 'fa-solid fa-g',
        dot: 'bg-orange-400',
    },
    'freehire.dev': {
        color: 'bg-emerald-900/50 border-emerald-700/50 text-emerald-300',
        icon: 'fa-solid fa-globe',
        dot: 'bg-emerald-400',
    },
};

async function loadSmartTerms() {
    const container = document.getElementById('smart-terms-chips');
    if (!container) return;
    try {
        const res = await fetch('/api/job-search/smart-terms');
        const data = await res.json();
        const terms = data.terms || [];
        if (terms.length === 0) {
            container.innerHTML = '<span class="text-xs text-slate-500 italic">Preencha seu Perfil para gerar termos automaticamente.</span>';
            return;
        }
        container.innerHTML = terms.map(t =>
            `<span class="bg-slate-800 border border-slate-600 text-slate-200 px-3 py-1 rounded-full text-xs font-medium flex items-center gap-1.5">
                <i class="fa-solid fa-tag text-purple-400 text-[10px]"></i> ${t}
            </span>`
        ).join('');
    } catch (e) {
        container.innerHTML = '<span class="text-xs text-red-400">Erro ao carregar termos.</span>';
    }
}

async function runSmartSearch() {
    const btn = document.getElementById('btn-smart-search');
    const loader = document.getElementById('smart-search-loader');
    const errorBox = document.getElementById('smart-search-error');
    const idle = document.getElementById('smart-search-idle');
    const summary = document.getElementById('smart-search-summary');
    const termsUsed = document.getElementById('smart-terms-used');
    const resultsGrid = document.getElementById('smart-search-results');

    const prompt = (document.getElementById('smart-search-prompt')?.value || '').trim();
    const location = document.getElementById('smart-filter-location')?.value || 'Brasil';
    const workMode = document.getElementById('smart-filter-workmode')?.value || null;
    const jobageRaw = document.getElementById('smart-filter-jobage')?.value || '';

    const body = {
        prompt: prompt || null,
        location: location,
        work_mode: workMode || null,
        jobage: jobageRaw ? parseInt(jobageRaw) : null,
    };

    // Reset UI
    btn.disabled = true;
    btn.innerHTML = '<i class="fa-solid fa-circle-notch fa-spin"></i> Buscando...';
    loader.classList.remove('hidden');
    errorBox.classList.add('hidden');
    idle.classList.add('hidden');
    summary.classList.add('hidden');
    termsUsed.classList.add('hidden');
    resultsGrid.classList.add('hidden');
    resultsGrid.innerHTML = '';

    // Cycle loading messages
    const statusEl = document.getElementById('smart-search-status-msg');
    const messages = [
        'Consultando LinkedIn...',
        'Buscando no Gupy (vagas brasileiras)...',
        'Consultando freehire.dev...',
        'Calculando compatibilidade com seu perfil...',
    ];
    let msgIdx = 0;
    const msgInterval = setInterval(() => {
        if (statusEl) statusEl.textContent = messages[msgIdx % messages.length];
        msgIdx++;
    }, 2500);

    try {
        const res = await fetch('/api/job-search/smart-search', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        });
        const data = await res.json();
        clearInterval(msgInterval);
        loader.classList.add('hidden');

        if (!res.ok) {
            document.getElementById('smart-search-error-msg').textContent =
                data.detail || 'Erro inesperado. Tente novamente.';
            errorBox.classList.remove('hidden');
            return;
        }

        smartSearchResults = data.results || [];
        const terms = data.terms_used || [];

        if (smartSearchResults.length === 0) {
            document.getElementById('smart-search-error-msg').textContent =
                'Nenhuma vaga encontrada para os termos detectados. Tente refinar com um prompt ou ajuste seu perfil.';
            errorBox.classList.remove('hidden');
            return;
        }

        // Show summary
        document.getElementById('smart-results-count').textContent = smartSearchResults.length;
        document.getElementById('smart-search-timestamp').textContent =
            `${new Date().toLocaleTimeString('pt-BR')} · ${location}`;

        // Source badges
        const sourceCounts = {};
        smartSearchResults.forEach(j => sourceCounts[j.source] = (sourceCounts[j.source] || 0) + 1);
        document.getElementById('smart-source-badges').innerHTML = Object.entries(sourceCounts)
            .map(([src, cnt]) => {
                const cfg = SOURCE_CONFIG[src] || { color: 'bg-slate-800 border-slate-600 text-slate-300', icon: 'fa-solid fa-circle', dot: 'bg-slate-400' };
                return `<span class="border ${cfg.color} px-2.5 py-0.5 rounded-full text-xs font-medium flex items-center gap-1.5">
                    <span class="w-1.5 h-1.5 rounded-full ${cfg.dot}"></span>${src} (${cnt})
                </span>`;
            }).join('');

        // Terms used chips
        if (terms.length > 0) {
            termsUsed.innerHTML = '<span class="text-xs text-slate-500">Buscado com:</span>' +
                terms.map(t => `<span class="bg-purple-900/40 border border-purple-700/40 text-purple-300 px-2 py-0.5 rounded-md text-xs">${t}</span>`).join('');
            termsUsed.classList.remove('hidden');
        }

        summary.classList.remove('hidden');
        resultsGrid.classList.remove('hidden');
        renderSmartResults(smartSearchResults);

    } catch (e) {
        clearInterval(msgInterval);
        loader.classList.add('hidden');
        document.getElementById('smart-search-error-msg').textContent =
            'Falha de conexão com o servidor. Verifique e tente novamente.';
        errorBox.classList.remove('hidden');
        console.error('Smart search error:', e);
    } finally {
        btn.disabled = false;
        btn.innerHTML = '<i class="fa-solid fa-magnifying-glass-chart"></i> Buscar Vagas';
    }
}

function fitScoreColor(score) {
    if (score >= 60) return 'text-emerald-400 border-emerald-600/50 bg-emerald-900/30';
    if (score >= 30) return 'text-yellow-400 border-yellow-600/50 bg-yellow-900/20';
    return 'text-slate-400 border-slate-600/50 bg-slate-900/40';
}

function workModelBadge(wm) {
    const map = {
        'Remoto': 'bg-emerald-900/50 text-emerald-300 border-emerald-700/50',
        'Híbrido': 'bg-blue-900/50 text-blue-300 border-blue-700/50',
        'Presencial': 'bg-amber-900/50 text-amber-300 border-amber-700/50',
    };
    return map[wm] || 'bg-slate-800 text-slate-400 border-slate-600';
}

function renderSmartResults(results) {
    const grid = document.getElementById('smart-search-results');
    if (!grid) return;
    grid.innerHTML = '';

    results.forEach((job, i) => {
        const srcCfg = SOURCE_CONFIG[job.source] || { color: 'bg-slate-800 border-slate-600 text-slate-300', icon: 'fa-solid fa-globe', dot: 'bg-slate-400' };
        const fitColors = fitScoreColor(job.fit_score);
        const wmBadge = workModelBadge(job.work_model);
        const postedDate = job.posted_at ? new Date(job.posted_at).toLocaleDateString('pt-BR') : '';
        const desc = job.description ? job.description.substring(0, 150) + (job.description.length > 150 ? '...' : '') : '';
        const skills = job.skills_required
            ? job.skills_required.split(',').slice(0, 4).map(s =>
                `<span class="bg-slate-900 border border-slate-700 text-slate-400 px-1.5 py-0.5 rounded text-[10px]">${s.trim()}</span>`
              ).join('')
            : '';

        const card = document.createElement('div');
        card.className = 'bg-slate-900/70 border border-slate-700/60 rounded-2xl p-4 flex flex-col gap-3 hover:border-slate-500/80 transition-all hover:shadow-xl hover:-translate-y-0.5 duration-200';
        card.innerHTML = `
            <!-- Card header -->
            <div class="flex items-start justify-between gap-2">
                <div class="flex-1 min-w-0">
                    <div class="flex items-center gap-2 mb-1 flex-wrap">
                        <!-- Source badge -->
                        <span class="border text-[10px] font-bold px-2 py-0.5 rounded-full flex items-center gap-1 ${srcCfg.color}">
                            <i class="${srcCfg.icon} text-[9px]"></i> ${job.source}
                        </span>
                        ${job.seniority ? `<span class="text-[10px] text-slate-500">${job.seniority}</span>` : ''}
                    </div>
                    <h4 class="text-sm font-bold text-white leading-snug line-clamp-2">${job.title}</h4>
                    <p class="text-xs text-slate-400 mt-0.5 truncate">${job.company}</p>
                </div>
                <!-- Fit Score -->
                <div class="flex-shrink-0 text-center border rounded-xl px-2.5 py-1.5 ${fitColors}">
                    <div class="text-base font-black leading-none">${job.fit_score}%</div>
                    <div class="text-[9px] font-semibold uppercase tracking-wide leading-none mt-0.5 opacity-70">fit</div>
                </div>
            </div>

            <!-- Location & work mode -->
            <div class="flex items-center gap-2 flex-wrap">
                <span class="text-xs text-slate-500 flex items-center gap-1">
                    <i class="fa-solid fa-location-dot text-slate-600"></i> ${job.location}
                </span>
                <span class="border text-[10px] px-2 py-0.5 rounded-full ${wmBadge}">${job.work_model}</span>
                ${job.salary ? `<span class="text-[10px] text-emerald-400 font-medium flex items-center gap-1"><i class="fa-solid fa-circle-dollar-to-slot"></i> ${job.salary}</span>` : ''}
                ${postedDate ? `<span class="text-[10px] text-slate-600">${postedDate}</span>` : ''}
            </div>

            <!-- Description -->
            ${desc ? `<p class="text-xs text-slate-500 leading-relaxed line-clamp-3">${desc}</p>` : ''}

            <!-- Skills -->
            ${skills ? `<div class="flex flex-wrap gap-1">${skills}</div>` : ''}

            <!-- Actions -->
            <div class="flex gap-2 mt-auto pt-1">
                <a href="${job.link}" target="_blank" rel="noopener noreferrer"
                   class="flex-1 text-center bg-sky-600/20 hover:bg-sky-600/40 border border-sky-600/40 text-sky-300 text-xs font-semibold py-2 rounded-lg transition-all flex items-center justify-center gap-1.5">
                    <i class="fa-solid fa-arrow-up-right-from-square"></i> Ver Vaga
                </a>
                <button onclick="saveJobFromSmartSearch(this, ${i})"
                        class="bg-purple-600/20 hover:bg-purple-600/40 border border-purple-600/40 text-purple-300 text-xs font-semibold py-2 px-3 rounded-lg transition-all flex items-center gap-1.5">
                    <i class="fa-solid fa-bookmark"></i> Salvar
                </button>
            </div>
        `;
        grid.appendChild(card);
    });
}

function sortSmartResults() {
    const sortBy = document.getElementById('smart-sort-select')?.value || 'fit';
    const sorted = [...smartSearchResults];
    if (sortBy === 'fit') sorted.sort((a, b) => b.fit_score - a.fit_score);
    else if (sortBy === 'title') sorted.sort((a, b) => a.title.localeCompare(b.title, 'pt'));
    else if (sortBy === 'company') sorted.sort((a, b) => a.company.localeCompare(b.company, 'pt'));
    else if (sortBy === 'source') sorted.sort((a, b) => a.source.localeCompare(b.source));
    renderSmartResults(sorted);
}

async function saveJobFromSmartSearch(btn, index) {
    const job = smartSearchResults[index];
    if (!job) return;
    btn.disabled = true;
    btn.innerHTML = '<i class="fa-solid fa-circle-notch fa-spin"></i>';
    try {
        const res = await fetch('/api/job-search/jobs/save-from-search', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                title: job.title,
                company: job.company,
                location: job.location,
                work_model: job.work_model,
                salary: job.salary,
                link: job.link,
                skills_required: job.skills_required,
                description: job.description,
                fit_score: job.fit_score,
                notes: `Encontrado via ${job.source} · Busca: "${job.query_used}"`,
            }),
        });
        if (res.ok) {
            btn.innerHTML = '<i class="fa-solid fa-check"></i> Salvo';
            btn.className = btn.className.replace('purple', 'emerald');
            showToast(`✅ "${job.title}" salvo no Board de Vagas!`, 'success');
        } else {
            const err = await res.json();
            btn.disabled = false;
            btn.innerHTML = '<i class="fa-solid fa-bookmark"></i> Salvar';
            showToast(err.detail || 'Erro ao salvar vaga.', 'error');
        }
    } catch (e) {
        btn.disabled = false;
        btn.innerHTML = '<i class="fa-solid fa-bookmark"></i> Salvar';
        showToast('Erro de conexão.', 'error');
    }
}

// =========================================================================
// --- MÓDULO DE ANÁLISE FINANCEIRA & FATURA NUBANK ---
// =========================================================================

let currentFinanceMonth = 'Todos';
let financeTransactions = [];
let monthlyChartInstance = null;
let categoryChartInstance = null;
let currentImportTab = 'file';

const categoryMeta = {
    "Entradas": { icon: "fa-arrow-down-long", color: "#22c55e", bg: "bg-emerald-500/10", text: "text-emerald-400", border: "border-emerald-500/30" },
    "Alimentação": { icon: "fa-utensils", color: "#f97316", bg: "bg-orange-500/10", text: "text-orange-400", border: "border-orange-500/30" },
    "Transporte": { icon: "fa-car", color: "#38bdf8", bg: "bg-sky-500/10", text: "text-sky-400", border: "border-sky-500/30" },
    "Moradia": { icon: "fa-house", color: "#a855f7", bg: "bg-purple-500/10", text: "text-purple-400", border: "border-purple-500/30" },
    "Assinaturas & Lazer": { icon: "fa-film", color: "#ec4899", bg: "bg-pink-500/10", text: "text-pink-400", border: "border-pink-500/30" },
    "Compras": { icon: "fa-bag-shopping", color: "#eab308", bg: "bg-yellow-500/10", text: "text-yellow-400", border: "border-yellow-500/30" },
    "Saúde": { icon: "fa-heart-pulse", color: "#ef4444", bg: "bg-rose-500/10", text: "text-rose-400", border: "border-rose-500/30" },
    "Educação": { icon: "fa-graduation-cap", color: "#10b981", bg: "bg-emerald-500/10", text: "text-emerald-400", border: "border-emerald-500/30" },
    "Serviços & Tarifas": { icon: "fa-receipt", color: "#64748b", bg: "bg-slate-500/10", text: "text-slate-400", border: "border-slate-500/30" },
    "Outros": { icon: "fa-box-archive", color: "#94a3b8", bg: "bg-slate-700/30", text: "text-slate-300", border: "border-slate-600" }
};

function formatCurrency(val) {
    return Number(val || 0).toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' });
}

function formatDateBR(dateStr) {
    if (!dateStr) return '';
    const parts = dateStr.split('-');
    if (parts.length === 3) {
        return `${parts[2]}/${parts[1]}/${parts[0]}`;
    }
    return dateStr;
}

// Carregar Dados Financeiros Principais
async function loadFinanceData(month = null) {
    const targetMonth = month || currentFinanceMonth || 'Todos';
    try {
        const [summaryRes, txRes] = await Promise.all([
            fetch(`/api/finances/summary?month=${encodeURIComponent(targetMonth)}`),
            fetch(`/api/finances/transactions?month=${encodeURIComponent(targetMonth)}`)
        ]);

        if (summaryRes.ok && txRes.ok) {
            const summary = await summaryRes.json();
            financeTransactions = await txRes.json();

            updateFinanceMonthSelect(summary.available_months, targetMonth);
            updateFinanceMetricCards(summary);
            renderFinanceCharts(summary);
            renderCategoryBreakdown(summary.categories_breakdown, summary.total_spent);
            filterFinanceTransactions();
        }
    } catch (e) {
        console.error("Erro ao carregar dados financeiros:", e);
        showToast("Erro ao carregar análise financeira.", "error");
    }
}

// Atualizar Seletor de Meses
function updateFinanceMonthSelect(availableMonths, selectedMonth) {
    const select = document.getElementById('finance-month-select');
    if (!select) return;

    let html = `<option value="Todos" ${selectedMonth === 'Todos' ? 'selected' : ''}>📅 Todos os Meses</option>`;
    (availableMonths || []).forEach(m => {
        const [year, month] = m.split('-');
        const monthNames = ["Jan", "Fev", "Mar", "Abr", "Mai", "Jun", "Jul", "Ago", "Set", "Out", "Nov", "Dez"];
        const label = `${monthNames[parseInt(month, 10) - 1]}/${year}`;
        html += `<option value="${m}" ${selectedMonth === m ? 'selected' : ''}>${label} (${m})</option>`;
    });
    select.innerHTML = html;
}

function handleFinanceMonthChange() {
    const select = document.getElementById('finance-month-select');
    currentFinanceMonth = select.value;
    loadFinanceData(currentFinanceMonth);
}

// Atualizar Cards de Métricas
function updateFinanceMetricCards(summary) {
    // 1. Total Entradas (Receitas)
    const incomeEl = document.getElementById('fin-stat-income');
    if (incomeEl) {
        incomeEl.innerText = `+ ${formatCurrency(summary.total_income)}`;
    }

    // 2. Total Saídas (Despesas)
    const totalEl = document.getElementById('fin-stat-total');
    if (totalEl) {
        totalEl.innerText = `- ${formatCurrency(summary.total_spent)}`;
    }

    // 3. Saldo Líquido
    const balanceEl = document.getElementById('fin-stat-balance');
    if (balanceEl) {
        const isPos = (summary.net_balance || 0) >= 0;
        balanceEl.innerText = `${isPos ? '+' : ''} ${formatCurrency(summary.net_balance)}`;
        balanceEl.className = isPos ? 'text-2xl font-bold text-emerald-400' : 'text-2xl font-bold text-rose-400';
    }

    // 4. Média de Gastos
    const avgEl = document.getElementById('fin-stat-avg');
    if (avgEl) {
        avgEl.innerText = `${formatCurrency(summary.avg_monthly)}/mês`;
    }

    const subEl = document.getElementById('fin-stat-total-sub');
    if (subEl) {
        if (summary.selected_month && summary.selected_month !== 'Todos') {
            subEl.innerText = `referente ao mês ${summary.selected_month}`;
        } else {
            subEl.innerText = 'acumulado no período';
        }
    }
}

// Renderizar Gráficos com Chart.js
function renderFinanceCharts(summary) {
    // 1. Gráfico de Evolução Mensal (Comparativo: Entradas vs Saídas)
    const monthlyCanvas = document.getElementById('finance-monthly-chart');
    if (monthlyCanvas && summary.monthly_breakdown) {
        if (monthlyChartInstance) monthlyChartInstance.destroy();

        const labels = summary.monthly_breakdown.map(item => {
            const [y, m] = item.month_year.split('-');
            const monthNames = ["Jan", "Fev", "Mar", "Abr", "Mai", "Jun", "Jul", "Ago", "Set", "Out", "Nov", "Dez"];
            return `${monthNames[parseInt(m, 10) - 1]}/${y.substring(2)}`;
        });
        const incomeValues = summary.monthly_breakdown.map(item => item.total_income || 0);
        const expenseValues = summary.monthly_breakdown.map(item => item.total_expense || item.total || 0);

        monthlyChartInstance = new Chart(monthlyCanvas, {
            type: 'bar',
            data: {
                labels: labels.length ? labels : ['Sem dados'],
                datasets: [
                    {
                        label: '🟢 Entradas (R$)',
                        data: incomeValues.length ? incomeValues : [0],
                        backgroundColor: 'rgba(34, 197, 94, 0.8)',
                        borderColor: '#22c55e',
                        borderWidth: 1.5,
                        borderRadius: 6,
                        maxBarThickness: 32
                    },
                    {
                        label: '🔴 Saídas (R$)',
                        data: expenseValues.length ? expenseValues : [0],
                        backgroundColor: 'rgba(245, 158, 11, 0.8)',
                        borderColor: '#f59e0b',
                        borderWidth: 1.5,
                        borderRadius: 6,
                        maxBarThickness: 32
                    }
                ]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: {
                        display: true,
                        position: 'top',
                        labels: {
                            color: '#cbd5e1',
                            font: { size: 11 },
                            boxWidth: 12,
                            padding: 10
                        }
                    },
                    tooltip: {
                        callbacks: {
                            label: (ctx) => ` ${ctx.dataset.label}: ${formatCurrency(ctx.raw)}`
                        }
                    }
                },
                scales: {
                    x: {
                        grid: { color: 'rgba(51, 65, 85, 0.4)' },
                        ticks: { color: '#94a3b8', font: { size: 11 } }
                    },
                    y: {
                        grid: { color: 'rgba(51, 65, 85, 0.4)' },
                        ticks: {
                            color: '#94a3b8',
                            font: { size: 11 },
                            callback: (v) => `R$ ${v}`
                        }
                    }
                }
            }
        });
    }

    // 2. Gráfico de Distribuição por Categoria de Despesa (Doughnut Chart)
    const categoryCanvas = document.getElementById('finance-category-chart');
    if (categoryCanvas && summary.categories_breakdown) {
        if (categoryChartInstance) categoryChartInstance.destroy();

        const cats = summary.categories_breakdown;
        const catLabels = cats.map(c => c.category);
        const catData = cats.map(c => c.total);
        const catColors = cats.map(c => (categoryMeta[c.category] ? categoryMeta[c.category].color : '#94a3b8'));

        categoryChartInstance = new Chart(categoryCanvas, {
            type: 'doughnut',
            data: {
                labels: catLabels.length ? catLabels : ['Sem dados'],
                datasets: [{
                    data: catData.length ? catData : [1],
                    backgroundColor: catColors.length ? catColors : ['#334155'],
                    borderWidth: 2,
                    borderColor: '#1e293b'
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: {
                        position: 'bottom',
                        labels: {
                            color: '#cbd5e1',
                            font: { size: 10 },
                            boxWidth: 12,
                            padding: 10
                        }
                    },
                    tooltip: {
                        callbacks: {
                            label: (ctx) => ` ${ctx.label}: ${formatCurrency(ctx.raw)}`
                        }
                    }
                },
                cutout: '68%'
            }
        });
    }
}

// Renderizar Painel de Categorias com Barras de Progresso
function renderCategoryBreakdown(categories, totalSpent) {
    const container = document.getElementById('finance-categories-grid');
    if (!container) return;

    if (!categories || categories.length === 0) {
        container.innerHTML = `
            <div class="col-span-full py-6 text-center text-slate-500 text-sm">
                Nenhum gasto registrado. Importe uma fatura para ver as despesas por categoria.
            </div>
        `;
        return;
    }

    container.innerHTML = categories.map(cat => {
        const meta = categoryMeta[cat.category] || categoryMeta["Outros"];
        return `
            <div class="bg-slate-900/70 border border-slate-700/60 rounded-xl p-4 flex flex-col justify-between shadow-sm hover:border-slate-600 transition-all">
                <div class="flex items-center justify-between mb-2">
                    <span class="inline-flex items-center gap-2 text-xs font-semibold ${meta.text}">
                        <i class="fa-solid ${meta.icon}"></i> ${cat.category}
                    </span>
                    <span class="text-xs font-bold text-slate-300">${cat.percentage}%</span>
                </div>
                <div class="space-y-1.5">
                    <p class="text-lg font-bold text-white">${formatCurrency(cat.total)}</p>
                    <div class="w-full bg-slate-800 rounded-full h-1.5 overflow-hidden">
                        <div class="h-full rounded-full transition-all duration-500" style="width: ${cat.percentage}%; background-color: ${meta.color};"></div>
                    </div>
                </div>
            </div>
        `;
    }).join('');
}

// Filtrar e Renderizar Tabela de Lançamentos
function filterFinanceTransactions() {
    const search = (document.getElementById('finance-search-input')?.value || '').toLowerCase().trim();
    const category = document.getElementById('finance-category-filter')?.value || 'Todas';
    const txType = document.getElementById('finance-type-filter')?.value || 'all';

    let filtered = financeTransactions;

    if (txType !== 'all') {
        filtered = filtered.filter(t => (t.transaction_type || 'expense') === txType);
    }

    if (category !== 'Todas') {
        filtered = filtered.filter(t => t.category === category);
    }

    if (search) {
        filtered = filtered.filter(t => 
            (t.title && t.title.toLowerCase().includes(search)) ||
            (t.payment_method && t.payment_method.toLowerCase().includes(search))
        );
    }

    renderFinanceTable(filtered);
}

function renderFinanceTable(transactions) {
    const tbody = document.getElementById('finance-tbody');
    const countEl = document.getElementById('finance-table-count');
    if (!tbody) return;

    if (countEl) {
        countEl.innerText = `${transactions.length} lançamentos`;
    }

    if (!transactions || transactions.length === 0) {
        tbody.innerHTML = `
            <tr>
                <td colspan="7" class="py-10 text-center text-slate-500">
                    Nenhuma movimentação encontrada com os filtros selecionados.
                </td>
            </tr>
        `;
        return;
    }

    const availableCategories = Object.keys(categoryMeta);

    tbody.innerHTML = transactions.map(t => {
        const isIncome = (t.transaction_type === 'income');
        const meta = categoryMeta[t.category] || (isIncome ? categoryMeta["Entradas"] : categoryMeta["Outros"]);
        
        const catOptions = availableCategories.map(c => `
            <option value="${c}" ${c === t.category ? 'selected' : ''}>${c}</option>
        `).join('');

        return `
            <tr class="hover:bg-slate-700/20 transition-colors">
                <td class="py-3 px-4 text-xs text-slate-400 whitespace-nowrap">
                    ${formatDateBR(t.date)}
                </td>
                <td class="py-3 px-4 font-medium text-white">
                    ${t.title}
                </td>
                <td class="py-3 px-4 text-center">
                    <button onclick="handleToggleTransactionType(${t.id}, '${isIncome ? 'expense' : 'income'}')" 
                            class="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-bold transition-all ${
                                isIncome 
                                    ? 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/30 hover:bg-emerald-500/30' 
                                    : 'bg-rose-500/20 text-rose-400 border border-rose-500/30 hover:bg-rose-500/30'
                            }" title="Clique para alternar entre Entrada e Saída">
                        <i class="fa-solid ${isIncome ? 'fa-arrow-down' : 'fa-arrow-up'}"></i>
                        ${isIncome ? 'Entrada' : 'Saída'}
                    </button>
                </td>
                <td class="py-3 px-4">
                    <select onchange="handleUpdateTransactionCategory(${t.id}, this.value)" 
                            class="bg-slate-900 border ${meta.border} ${meta.text} text-xs font-semibold rounded-lg px-2.5 py-1 focus:outline-none cursor-pointer">
                        ${catOptions}
                    </select>
                </td>
                <td class="py-3 px-4 text-xs text-slate-400">
                    ${t.payment_method || 'Cartão Nubank'}
                </td>
                <td class="py-3 px-4 text-right font-bold whitespace-nowrap ${isIncome ? 'text-emerald-400' : 'text-rose-400'}">
                    ${isIncome ? '+' : '-'} ${formatCurrency(t.amount)}
                </td>
                <td class="py-3 px-4 text-center">
                    <button onclick="handleDeleteTransaction(${t.id})" class="text-slate-500 hover:text-rose-400 transition-colors p-1" title="Excluir Lançamento">
                        <i class="fa-solid fa-trash-can text-xs"></i>
                    </button>
                </td>
            </tr>
        `;
    }).join('');
}

// Alternar Tipo de Transação (Entrada <-> Saída)
async function handleToggleTransactionType(txId, newType) {
    try {
        const updateData = { transaction_type: newType };
        if (newType === 'income') {
            updateData.category = 'Entradas';
        }
        const res = await fetch(`/api/finances/transactions/${txId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(updateData)
        });

        if (res.ok) {
            showToast(`Movimentação alterada para ${newType === 'income' ? 'Entrada (+)' : 'Saída (-)'}!`);
            loadFinanceData(currentFinanceMonth);
        } else {
            showToast('Erro ao alternar tipo.', 'error');
        }
    } catch (e) {
        showToast('Erro de conexão.', 'error');
    }
}


// Alteração Inline de Categoria
async function handleUpdateTransactionCategory(txId, newCategory) {
    try {
        const res = await fetch(`/api/finances/transactions/${txId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ category: newCategory })
        });

        if (res.ok) {
            showToast(`Categoria atualizada para "${newCategory}"!`);
            // Recarregar dados para recalcular somas e gráficos
            loadFinanceData(currentFinanceMonth);
        } else {
            showToast('Erro ao atualizar categoria.', 'error');
        }
    } catch (e) {
        showToast('Erro de conexão ao atualizar.', 'error');
    }
}

// Excluir Lançamento Individual
async function handleDeleteTransaction(txId) {
    if (!confirm('Deseja realmente excluir este lançamento?')) return;

    try {
        const res = await fetch(`/api/finances/transactions/${txId}`, { method: 'DELETE' });
        if (res.ok) {
            showToast('Lançamento excluído com sucesso.');
            loadFinanceData(currentFinanceMonth);
            loadStats();
        } else {
            showToast('Erro ao excluir lançamento.', 'error');
        }
    } catch (e) {
        showToast('Erro de conexão ao excluir.', 'error');
    }
}

// Limpar Lançamentos
async function handleClearFinances() {
    const isFiltered = currentFinanceMonth && currentFinanceMonth !== 'Todos';
    const msg = isFiltered 
        ? `Deseja apagar TODOS os lançamentos do mês ${currentFinanceMonth}?`
        : 'Deseja apagar TODOS os lançamentos financeiros importados no sistema?';

    if (!confirm(msg)) return;

    try {
        const url = isFiltered 
            ? `/api/finances/clear?month=${encodeURIComponent(currentFinanceMonth)}`
            : '/api/finances/clear';

        const res = await fetch(url, { method: 'DELETE' });
        if (res.ok) {
            const data = await res.json();
            showToast(data.message || 'Lançamentos apagados.');
            currentFinanceMonth = 'Todos';
            loadFinanceData('Todos');
            loadStats();
        } else {
            showToast('Erro ao limpar lançamentos.', 'error');
        }
    } catch (e) {
        showToast('Erro de conexão ao limpar.', 'error');
    }
}

// --- MODAL DE IMPORTAÇÃO DE FATURAS ---

function openUploadInvoiceModal() {
    document.getElementById('modal-import-invoice').classList.remove('hidden');
    switchImportTab('file');
}

function closeUploadInvoiceModal() {
    document.getElementById('modal-import-invoice').classList.add('hidden');
    document.getElementById('invoice-file-input').value = '';
    document.getElementById('selected-file-label').innerText = 'Nenhum arquivo selecionado';
    document.getElementById('invoice-paste-textarea').value = '';
}

function switchImportTab(tab) {
    currentImportTab = tab;
    const btnFile = document.getElementById('btn-import-tab-file');
    const btnPaste = document.getElementById('btn-import-tab-paste');
    const paneFile = document.getElementById('import-pane-file');
    const panePaste = document.getElementById('import-pane-paste');

    if (tab === 'file') {
        btnFile.className = 'flex-1 py-2 text-xs font-semibold rounded-lg bg-amber-600 text-white transition-all';
        btnPaste.className = 'flex-1 py-2 text-xs font-semibold rounded-lg text-slate-400 hover:text-white transition-all';
        paneFile.classList.remove('hidden');
        panePaste.classList.add('hidden');
    } else {
        btnPaste.className = 'flex-1 py-2 text-xs font-semibold rounded-lg bg-amber-600 text-white transition-all';
        btnFile.className = 'flex-1 py-2 text-xs font-semibold rounded-lg text-slate-400 hover:text-white transition-all';
        panePaste.classList.remove('hidden');
        paneFile.classList.add('hidden');
    }
}

function handleFileSelected(event) {
    const file = event.target.files[0];
    const label = document.getElementById('selected-file-label');
    if (file) {
        label.innerText = `📄 ${file.name} (${(file.size / 1024).toFixed(1)} KB)`;
        label.className = 'inline-block bg-amber-500/20 text-amber-300 text-xs px-3 py-1.5 rounded-lg border border-amber-500/30';
    } else {
        label.innerText = 'Nenhum arquivo selecionado';
        label.className = 'inline-block bg-slate-800 text-amber-300 text-xs px-3 py-1.5 rounded-lg border border-slate-700';
    }
}

async function handleUploadInvoiceFile(event) {
    event.preventDefault();
    const fileInput = document.getElementById('invoice-file-input');
    const file = fileInput.files[0];

    if (!file) {
        showToast('Por favor, selecione um arquivo CSV ou OFX da fatura.', 'error');
        return;
    }

    const btn = document.getElementById('btn-submit-upload');
    btn.disabled = true;
    btn.innerHTML = '<i class="fa-solid fa-circle-notch fa-spin"></i> Processando...';

    const formData = new FormData();
    formData.append('file', file);

    try {
        const res = await fetch('/api/finances/upload', {
            method: 'POST',
            body: formData
        });

        if (res.ok) {
            const data = await res.json();
            showToast(data.message || `${data.imported_count} transações importadas com sucesso!`, 'success');
            closeUploadInvoiceModal();
            loadFinanceData();
            loadStats();
        } else {
            const err = await res.json();
            showToast(err.detail || 'Erro ao processar arquivo.', 'error');
        }
    } catch (e) {
        showToast('Erro de conexão ao enviar arquivo.', 'error');
    } finally {
        btn.disabled = false;
        btn.innerHTML = '<i class="fa-solid fa-upload"></i> Processar Fatura';
    }
}

async function handlePasteInvoiceText(event) {
    event.preventDefault();
    const textarea = document.getElementById('invoice-paste-textarea');
    const content = textarea.value.trim();

    if (!content) {
        showToast('Cole o conteúdo da fatura antes de prosseguir.', 'error');
        return;
    }

    try {
        const res = await fetch('/api/finances/paste', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ content })
        });

        if (res.ok) {
            const data = await res.json();
            showToast(data.message || `${data.imported_count} transações importadas!`, 'success');
            closeUploadInvoiceModal();
            loadFinanceData();
            loadStats();
        } else {
            const err = await res.json();
            showToast(err.detail || 'Erro ao processar texto.', 'error');
        }
    } catch (e) {
        showToast('Erro de conexão ao enviar texto.', 'error');
    }
}

// --- MODAL DE GASTO MANUAL ---

function openAddTransactionModal() {
    document.getElementById('modal-finance-manual').classList.remove('hidden');
    document.getElementById('fin-manual-date').value = new Date().toISOString().split('T')[0];
}

function closeAddTransactionModal() {
    document.getElementById('modal-finance-manual').classList.add('hidden');
    document.getElementById('fin-manual-title').value = '';
    document.getElementById('fin-manual-amount').value = '';
}

function handleManualTypeChange(type) {
    const catSelect = document.getElementById('fin-manual-category');
    if (!catSelect) return;
    if (type === 'income') {
        catSelect.value = 'Entradas';
    } else if (catSelect.value === 'Entradas') {
        catSelect.value = 'Outros';
    }
}

async function handleAddManualTransaction(event) {
    event.preventDefault();
    const date = document.getElementById('fin-manual-date').value;
    const title = document.getElementById('fin-manual-title').value.trim();
    const amount = parseFloat(document.getElementById('fin-manual-amount').value);
    const txType = document.getElementById('fin-manual-type')?.value || 'expense';
    const category = document.getElementById('fin-manual-category').value;
    const method = document.getElementById('fin-manual-method').value.trim() || 'Cartão Nubank';

    if (!title || isNaN(amount) || amount <= 0) {
        showToast('Preencha os campos obrigatórios corretamente.', 'error');
        return;
    }

    try {
        const res = await fetch('/api/finances/transactions', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                date,
                title,
                amount,
                transaction_type: txType,
                category,
                payment_method: method
            })
        });

        if (res.ok) {
            showToast('Lançamento salvo com sucesso!');
            closeAddTransactionModal();
            loadFinanceData(currentFinanceMonth);
            loadStats();
        } else {
            const err = await res.json();
            showToast(err.detail || 'Erro ao cadastrar lançamento.', 'error');
        }
    } catch (e) {
        showToast('Erro de conexão.', 'error');
    }
}

// --- MODAL DE REGRAS DE CATEGORIZAÇÃO ---

function openRulesModal() {
    document.getElementById('modal-finance-rules').classList.remove('hidden');
    loadFinanceRules();
}

function closeRulesModal() {
    document.getElementById('modal-finance-rules').classList.add('hidden');
    document.getElementById('input-rule-keyword').value = '';
}

async function loadFinanceRules() {
    const listContainer = document.getElementById('finance-rules-list');
    if (!listContainer) return;

    try {
        const res = await fetch('/api/finances/rules');
        if (res.ok) {
            const rules = await res.json();
            if (rules.length === 0) {
                listContainer.innerHTML = '<p class="text-xs text-slate-500 italic p-2">Nenhuma regra customizada cadastrada ainda.</p>';
                return;
            }

            listContainer.innerHTML = rules.map(r => `
                <div class="flex items-center justify-between p-2 bg-slate-900/80 rounded-lg border border-slate-700/60 text-xs">
                    <div class="flex items-center gap-2">
                        <span class="font-mono text-purple-300 font-semibold">"${r.keyword}"</span>
                        <i class="fa-solid fa-arrow-right text-[10px] text-slate-500"></i>
                        <span class="text-slate-200">${r.category_name}</span>
                    </div>
                    <button onclick="handleDeleteRule(${r.id})" class="text-slate-500 hover:text-rose-400 transition-colors p-1" title="Excluir regra">
                        <i class="fa-solid fa-xmark"></i>
                    </button>
                </div>
            `).join('');
        }
    } catch (e) {
        listContainer.innerHTML = '<p class="text-xs text-rose-400">Erro ao carregar regras.</p>';
    }
}

async function handleAddRule(event) {
    event.preventDefault();
    const keywordInput = document.getElementById('input-rule-keyword');
    const categorySelect = document.getElementById('input-rule-category');

    const keyword = keywordInput.value.trim();
    const category_name = categorySelect.value;

    if (!keyword) return;

    try {
        const res = await fetch('/api/finances/rules', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ keyword, category_name })
        });

        if (res.ok) {
            const data = await res.json();
            showToast(data.message || 'Regra salva com sucesso!');
            keywordInput.value = '';
            loadFinanceRules();
            loadFinanceData(currentFinanceMonth);
        } else {
            const err = await res.json();
            showToast(err.detail || 'Erro ao cadastrar regra.', 'error');
        }
    } catch (e) {
        showToast('Erro de conexão.', 'error');
    }
}

async function handleDeleteRule(ruleId) {
    try {
        const res = await fetch(`/api/finances/rules/${ruleId}`, { method: 'DELETE' });
        if (res.ok) {
            showToast('Regra removida.');
            loadFinanceRules();
        } else {
            showToast('Erro ao excluir regra.', 'error');
        }
    } catch (e) {
        showToast('Erro de conexão.', 'error');
    }
}


