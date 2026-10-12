var endpoint = '/api/report/venda/rota/';
$.ajax({
	method: "GET",
	url: endpoint,
	success: function(data){
		Highcharts.chart('chart_rota', {
			chart: {type: 'column', styledMode: true},
			title: {text: '', align: 'left'},
			xAxis: {categories: data.label},
			yAxis: [{className: 'highcharts-color-0', title: {text: 'Total Bilhete'}, tickInterval: 1}],
			plotOptions: {column: {borderRadius: 5}},
			series: [{name: 'Total Bilhete', data: data.obj, tooltip: {valueSuffix: ' Bilhete'}}]
		});
	},
	error: function(error_data){
		console.log("error");
		console.log(error_data);
	}
});
