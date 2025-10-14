function renderScatterplot(tracks) {
  if (!tracks || tracks.length === 0) {
    return;
  }

  const margin = {top: 20, right: 20, bottom: 50, left: 50},
    width = 500 - margin.left - margin.right,
    height = 500 - margin.top - margin.bottom;

  d3.select("#scatterplot").selectAll("*").remove();

  const svg = d3.select("#scatterplot")
    .append("svg")
    .attr("width", width + margin.left + margin.right)
    .attr("height", height + margin.top + margin.bottom)
    .append("g")
    .attr("transform", `translate(${margin.left}, ${margin.top})`);

  const x = d3.scaleLinear()
    .domain([0, 1])
    .range([0, width]);
  svg.append("g")
    .attr("transform", `translate(0, ${height})`)
    .call(d3.axisBottom(x));
  svg.append("text")
    .attr("text-anchor", "end")
    .attr("x", width)
    .attr("y", height + margin.top + 15)
    .attr("class", "axis-label")
    .text("Valence (Positivity)")

  const y = d3.scaleLinear()
    .domain([0, 1])
    .range([height, 0]);
  svg.append("g")
    .call(d3.axisLeft(y));
  svg.append("text")
    .attr("text-anchor", "end")
    .attr("transform", "rotate(-90)")
    .attr("y", -margin.left + 15)
    .attr("x", -margin.top)
    .attr("class", "axis-label")
    .text("Energy");
  
  const tooltip = d3.select("body").append("div")
    .attr("class", "tooltip")

  // x-axis grid lines
  svg.append("g")
  .attr("class", "grid x-grid")
  .attr("transform", `translate(0, ${height})`)
  .call(d3.axisBottom(x)
    .tickSize(-height)
    .tickFormat("")
    .ticks(10)
  );

  // y-axis grid lines
  svg.append("g")
  .attr("class", "grid y-grid")
  .call(d3.axisLeft(y)
    .tickSize(-width)
    .tickFormat("")
    .ticks(10)          
  );


  svg.append('g')
    .selectAll("dot")
    .data(tracks)
    .enter()
    .append("circle")
      .attr("cx", d => x(d.valence))
      .attr("cy", d => y(d.energy))
      .attr("r", 5)     // radius of dots                
      .attr("class", "dot")
    .on("mouseover", (event, d) => {
      tooltip.transition().duration(200).style("opacity", .9);
      tooltip.html(`<strong>${d.name}</strong><br/>${d.artist}`)
        .style("left", (event.pageX + 10) + "px")
        .style("top", (event.pageY - 28) + "px");
    })
    .on("mouseout", d => {
      tooltip.transition().duration(500).style("opacity", 0);
    });

}