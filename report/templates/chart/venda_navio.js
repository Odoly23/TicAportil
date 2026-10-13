$.ajax({
	method: "GET",
	url: '/api/report/venda/navio/',
	success: function(data){
		Highcharts.chart('chart_navio', {
			chart: {type: 'column', styledMode: true},
			title: {text: '', align: 'left'},
			xAxis: {categories: data.label},
			yAxis: [{className: 'highcharts-color-0', title: {text: 'USD'}}, {className: 'highcharts-color-1', opposite: true, title: {text: ''}, tickInterval: 1}],
			plotOptions: {column: {borderRadius: 5}},
			series: [
				{name: 'USD', type: 'column', data: data.obj, tooltip: {valuePrefix: '$'}},
				{name: 'Bilhete', type: 'line', yAxis: 1, data: data.obj2}
			]
		});
	},
	error: function(error_data){ console.log("error"); console.log(error_data); }
});
