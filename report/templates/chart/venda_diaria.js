var endpoint = '/api/report/venda/diaria/';
$.ajax({
	method: "GET",
	url: endpoint,
	success: function(data){
		Highcharts.chart('chart_diaria', {
			chart: {type: 'line', styledMode: true},
			title: {text: '', align: 'left'},
			xAxis: {categories: data.label},
			yAxis: [{className: 'highcharts-color-0', title: {text: 'Bilhete'}, tickInterval: 1}],
			plotOptions: {column: {borderRadius: 5}},
			series: [{name: 'Bilhete', data: data.obj, tooltip: {valueSuffix: ' Bilhete'}}]
		});
	},
	error: function(error_data){
		console.log("error");
		console.log(error_data);
	}
});
