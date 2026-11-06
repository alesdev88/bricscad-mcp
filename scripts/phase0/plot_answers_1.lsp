;; First pass: answers to learn the prompts, then the output path once the order is known.
(setq *answers* (list "_Y" "Model" "Print As PDF.pc3" "" "" "" "" "_E" "_F" "_C" "_Y" "" "_Y" "" (strcat *dir* "out.pdf") "_N" "_Y"))
(load (strcat *here* "plot_pdf.lsp"))
