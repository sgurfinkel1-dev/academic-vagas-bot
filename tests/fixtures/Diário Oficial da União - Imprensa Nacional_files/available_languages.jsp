









AUI.add(
	'portal-available-languages',
	function(A) {
		var available = {};

		var direction = {};

		

			available['pt_BR'] = 'português (Brasil)';
			direction['pt_BR'] = 'ltr';

		

			available['en_US'] = 'inglês (Estados Unidos)';
			direction['en_US'] = 'ltr';

		

		Liferay.Language.available = available;
		Liferay.Language.direction = direction;
	},
	'',
	{
		requires: ['liferay-language']
	}
);