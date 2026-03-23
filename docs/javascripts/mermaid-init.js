document.addEventListener("DOMContentLoaded", async function () {
  if (typeof mermaid === "undefined") {
    return;
  }

  var mermaidBlocks = document.querySelectorAll("pre.mermaid");

  mermaidBlocks.forEach(function (block) {
    var code = block.querySelector("code");
    var source = code ? code.textContent : block.textContent;
    var diagram = document.createElement("div");

    diagram.className = "mermaid";
    diagram.textContent = source.trim();

    block.replaceWith(diagram);
  });

  mermaid.initialize({
    startOnLoad: false,
    securityLevel: "loose",
    theme: "default",
  });

  await mermaid.run({
    nodes: Array.from(document.querySelectorAll(".mermaid")),
  });
});
