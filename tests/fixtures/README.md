# Fixtures de teste

Coloque aqui o HTML salvo da página de busca do DOU.

## dou_busca.html

Salve a página de busca do DOU (ex.: busca por "professor") do navegador
como HTML completo e coloque neste arquivo. O teste `test_fontes.py::TestDouParse`
lê este arquivo para validar o parser do `jsonArray` embutido no `<script>`.

Sem este arquivo, o teste é **pulado** (não falha), porque o ponto do teste
é o contrato com o site real — fixture sintética não testa isso.
