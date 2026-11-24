$.ajax({
	method: "GET",
	url: '/api/report/venda/pagamentu/',
	success: function(data){
		Highcharts.chart('chart_pagamentu', {
			chart: {type: 'pie', styledMode: true},
			title: {text: '', align: 'left'},
			tooltip: {pointFormat: '<b>${point.y:.2f}</b> ({point.percentage:.1f}%)'},
			plotOptions: {pie: {dataLabels: {enabled: true, format: '{point.name}'}}},
			series: [{name: 'USD', data: data.label.map(function (l, i) { return {name: l, y: data.obj[i]}; })}]
		});
	},
	error: function(error_data){ console.log("error"); console.log(error_data); }
});
