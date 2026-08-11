# A busca do DOU cobre uma fatia estreita demais

Registro do diagnóstico feito em 11/08/2026, para a sessão que for corrigir.

## O sintoma

Concursos de professor que aparecem numa busca no Google — e no PCI Concursos,
que republica o DOU — não aparecem no painel. Exemplos reais trazidos pelo
usuário: UFOP, professor substituto em Lógica e Filosofia da Lógica, edital
PROGEP 22/2026; UFSC, professor efetivo em Lógica, edital 039/2025/DDP.

Não é falta de fonte nova: o PCI lê o DOU inteiro, e o app já consulta o DOU.
É a nossa leitura do DOU que é parcial.

## Os dois defeitos

Ambos estão na primeira linha de `src/sources/dou.py`:

```python
BUSCA = ("https://www.in.gov.br/consulta/-/buscar/dou?q=%22{termo}%22&s=do3&sortType=0"
         "&delta={delta}&exactDate=personalizado&publishFrom={desde}&publishTo={ate}")
```

**1. `s=do3` restringe à Seção 3.** Concurso para professor também sai nas
Seções 1 e 2 — aberturas, retificações, prorrogações de prazo, homologações.
Tudo fora da Seção 3 é invisível para o app, e sempre foi.

**2. Não há paginação.** `_itens()` lê só a primeira página, e `delta` é limitado
a 75 (`min(delta, 75)`). Uma busca por "docente" em 30 dias no Brasil inteiro
devolve muito mais que isso: o app fica com uma fatia e descarta o resto sem
emitir aviso. Com `sortType=0`, qual fatia sobra depende da ordenação do site.
Daí o padrão que o usuário descreve — acha algumas, perde outras, sem lógica
aparente.

## O que fazer

- Varrer as três seções (laço por `do1`, `do2`, `do3`, ou remover o parâmetro se
  o site aceitar busca sem recorte de seção).
- Paginar até esgotar o período ou bater um teto explícito, registrando no log
  quantas páginas vieram — truncar em silêncio foi o que escondeu o problema.
- Conferir o `sortType`: havendo corte, que seja por data, não por relevância
  do site.

## Como validar (não pule)

O retorno é um JSON embutido num `<script>` da página renderizada. Qualquer
suposição errada sobre esse formato quebra a fonte em silêncio — o `buscar()`
engole a exceção e devolve lista vazia. Então:

1. Rode contra o DOU real e registre **quantos itens vinham antes e quantos vêm
   depois**, por termo.
2. Confirme que os dois editais citados acima passam a ser encontrados.
3. Guarde uma amostra do HTML de resposta como fixture e escreva teste em cima
   dela, para a próxima mudança no site do DOU falhar alto, e não em silêncio.

## Domínios que a coleta precisa alcançar

Se a sessão rodar num ambiente com rede restrita, estes precisam estar
liberados (o `in.gov.br` é o essencial para este trabalho):

```
in.gov.br
*.in.gov.br
anpof.org.br
api.queridodiario.ok.org.br
*.gupy.io
vagas.com.br
fapesp.br
```

Mais os sites das universidades listadas em `config.yaml` (`paginas_concursos`
e `paginas_privadas`), se for mexer nessas fontes.

---

## Como a paginação funciona de verdade (capturado do navegador, 11/08/2026)

Clicando no "2" da paginação do próprio site, a URL que ele monta é:

```
.../buscar/dou?q=%22professor%22&s=do3&exactDate=personalizado&sortType=1
   &delta=20&currentPage=1&newPage=2
   &score=5.143003&id=717430054&displayDate=1783393200000
   &publishFrom=01%2F07%2F2026&publishTo=11%2F08%2F2026
```

Duas descobertas, e as duas explicam por que os palpites falharam:

**1. A paginação é por cursor, não por deslocamento.** Não existe `start` nem
`p` nem `offset`. O site usa `currentPage` + `newPage` acompanhados de um
cursor do ÚLTIMO item da página atual: `score`, `id` e `displayDate` (epoch em
milissegundos). É o padrão do Liferay. Por isso `start=20` vinha vazio e `p=1`
repetia a página: nenhum dos dois existe para o site.

Para implementar: os campos `score`, `id` e `displayDate` precisam sair do
próprio `jsonArray` do último item da página lida, e alimentar a URL da
próxima. Se algum desses campos não estiver no jsonArray, é preciso descobrir
onde o site os obtém antes de escrever o laço.

**2. As datas vão com barra, não com hífen.** O site manda
`publishFrom=01%2F07%2F2026` (ou seja, `01/07/2026`). O código usa
`01-07-2026`. Vale verificar se o hífen está sendo aceito por acaso ou se está
estreitando o resultado em silêncio.

## A dimensão do problema, medida

Para `"professor"`, Seção 3, de 01/07 a 11/08/2026, o site informa
**126 páginas** de resultados. O app lê **uma**. Menos de 1% — e é exatamente
essa a diferença entre o que o PCI Concursos mostra e o que o painel mostra.

## Recomendação

Implementar o cursor é possível, mas continua sendo raspagem de uma página que
pode mudar de formato sem aviso. Com 126 páginas em jogo, o caminho de fundo é
o **INLABS** (`src/sources/inlabs.py`, escrito e nunca ligado): dados oficiais
do DOU em XML, sem raspagem, sem parâmetro a descobrir e sem cursor a manter.
