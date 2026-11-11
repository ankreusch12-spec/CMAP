// Controle CMAP — o pouco de JavaScript da página.
// Fica num arquivo separado (e não dentro do HTML) por segurança:
// a política da página só permite scripts vindos daqui.

document.addEventListener("DOMContentLoaded", () => {
  filtrosDeColuna();
  abas();
  confirmacoes();
  gradeDeAssentos();
});

// 1) Caixinhas de filtro embaixo de cada coluna (igual às do CMAP).
function filtrosDeColuna() {
  document.querySelectorAll("table[data-filtravel]").forEach((tabela) => {
    const campos = tabela.querySelectorAll("[data-filtro]");
    const contador = document.querySelector("[data-contador]");
    const filtrar = () => {
      const termos = [...campos].map((c) => [Number(c.dataset.filtro), c.value.trim().toLowerCase()]);
      let visiveis = 0;
      tabela.querySelectorAll("tbody tr").forEach((linha) => {
        const ok = termos.every(([col, termo]) => {
          if (!termo) return true;
          const cel = linha.cells[col];
          const texto = cel ? (cel.dataset.valor ?? cel.textContent) : "";
          return texto.toLowerCase().includes(termo);
        });
        linha.hidden = !ok;
        if (ok) visiveis++;
      });
      if (contador) contador.textContent = `${visiveis} reserva(s)`;
    };
    campos.forEach((c) => c.addEventListener("input", filtrar));
  });
}

// 2) Abas Perfil | Assentos.
function abas() {
  const barra = document.querySelector("[data-abas]");
  if (!barra) return;
  barra.querySelectorAll("button").forEach((botao) => {
    botao.addEventListener("click", () => {
      barra.querySelectorAll("button").forEach((b) => b.classList.toggle("ativa", b === botao));
      document.querySelectorAll("[data-painel]").forEach((p) =>
        p.classList.toggle("oculto", p.dataset.painel !== botao.dataset.aba));
      history.replaceState(null, "", `?aba=${botao.dataset.aba}`);
    });
  });
}

// 3) Pergunta "tem certeza?" antes de excluir.
function confirmacoes() {
  document.querySelectorAll("form[data-confirmar]").forEach((form) => {
    form.addEventListener("submit", (e) => {
      if (!confirm(form.dataset.confirmar)) e.preventDefault();
    });
  });
}

// 4) Grade de assentos: totais automáticos, nova linha e "repetir 1º mês".
function gradeDeAssentos() {
  const corpo = document.querySelector("[data-corpo-grade]");
  if (!corpo) return;
  const totalLinhas = document.querySelector("[data-total-linhas]");

  const recalcular = () => {
    const porMes = {};
    corpo.querySelectorAll("tr").forEach((linha) => {
      let soma = 0;
      linha.querySelectorAll("input.qtd").forEach((campo) => {
        const n = parseInt(campo.value, 10) || 0;
        const mes = campo.name.split("_").pop();
        soma += n;
        porMes[mes] = (porMes[mes] || 0) + n;
      });
      const celula = linha.querySelector(".total-linha");
      if (celula) celula.textContent = soma;
    });
    document.querySelectorAll("[data-total-mes]").forEach((c) => {
      c.textContent = porMes[c.dataset.totalMes] || 0;
    });
  };

  // Quando a linha em branco recebe um Dept Code, cria outra linha em branco.
  const prepararLinhaNova = (linha) => {
    const dept = linha.querySelector('input[name^="dept_code_"]');
    dept.addEventListener("input", function criar() {
      if (!dept.value.trim()) return;
      dept.removeEventListener("input", criar);
      const indice = Number(totalLinhas.value);
      const copia = linha.cloneNode(true);
      copia.querySelectorAll("input").forEach((campo) => {
        campo.name = campo.name.replace(/_(\d+)(_|$)/, `_${indice}$2`);
        if (campo.classList.contains("qtd")) campo.value = "0";
        else if (campo.name.startsWith("shift_")) campo.value = "DED";
        else campo.value = "";
      });
      corpo.appendChild(copia);
      totalLinhas.value = indice + 1;
      prepararLinhaNova(copia);
    });
  };

  corpo.addEventListener("input", recalcular);
  corpo.querySelectorAll("[data-linha-modelo]").forEach(prepararLinhaNova);

  const repetir = document.querySelector("[data-repetir]");
  if (repetir) {
    repetir.addEventListener("click", () => {
      corpo.querySelectorAll("tr").forEach((linha) => {
        const campos = linha.querySelectorAll("input.qtd");
        campos.forEach((c) => { c.value = campos[0].value; });
      });
      recalcular();
    });
  }
  recalcular();
}
