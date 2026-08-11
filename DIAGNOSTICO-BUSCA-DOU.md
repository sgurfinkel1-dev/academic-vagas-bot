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
