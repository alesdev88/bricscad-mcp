;; Exporting, plotting and previews. Relies on the helpers in read.lsp and listener.lsp.
;; None of these change the drawing: see docs/phase-0-results.md, Phase 3.

;; Zooming and plotting mark a drawing as modified although nothing is stored.
;; The flag goes back to what it was, also when the worker fails.
(defun mcp:keep-clean (worker args / result message)
  (acad-push-dbmod)
  (setq *mcp-pending-error* nil
        result (vl-catch-all-apply worker args))
  (if (vl-catch-all-error-p result)
    (setq message (cond (*mcp-pending-error*) ((vl-catch-all-error-message result))))
  )
  (mcp:cancel-command)
  (acad-pop-dbmod)
  (if message
    (progn
      (setq *mcp-pending-error* message)
      (exit)
    )
  )
  result
)

;; The command must end inside this request, or the listener's _.DELAY becomes its next answer.
(defun mcp:export-dxf (path version)
  (mcp:keep-clean 'mcp:export-dxf-now (list path version))
)

(defun mcp:export-dxf-now (path version)
  (command "_.DXFOUT" path "_V" version "")
  (if (> (getvar "CMDACTIVE") 0)
    (mcp:fail (strcat "BricsCAD did not finish the DXF export: " (getvar "LASTPROMPT")))
  )
  T
)

;; ---- Plotting ----

(defun mcp:layout-names () (cons "Model" (layoutlist)))

;; The stored spelling of a layout, whatever the case of the name asked for.
(defun mcp:layout-named (name / found)
  (foreach candidate (mcp:layout-names)
    (if (= (strcase candidate) (strcase name)) (setq found candidate))
  )
  (if (null found)
    (mcp:fail (strcat "No layout named " name ". Layouts: " (mcp:join (mcp:layout-names) ", ") "."))
  )
  found
)

;; BricsCAD names a rejected answer: "Paper 'X' not found", "Stylesheet 'X' not found",
;; "X: plotter configuration not found". Other "not found" lines are warnings, such as
;; "None: plotter configuration not found" for a layout that has no device yet.
(defun mcp:rejected-p (answer prompt)
  (and (= (type answer) 'STR)
       (/= answer "")
       (or (vl-string-search (strcase (strcat "'" answer "' not found")) (strcase prompt))
           (vl-string-search (strcase (strcat answer ": plotter configuration not found")) (strcase prompt))))
)

;; A rejected answer makes BricsCAD ask again, and the next answer would then go to the wrong
;; question. So answers go one at a time and stop there.
(defun mcp:answer-all (answers / answer prompt)
  (while answers
    (setq answer (car answers)
          answers (cdr answers))
    (command answer)
    (setq prompt (getvar "LASTPROMPT"))
    (cond
      ((mcp:rejected-p answer prompt)
       (mcp:cancel-command)
       (mcp:fail (strcat "BricsCAD refused an answer: " prompt)))
      ((and answers (= (getvar "CMDACTIVE") 0))
       (mcp:fail (strcat "BricsCAD ended the command early: " prompt)))
    )
  )
  (if (> (getvar "CMDACTIVE") 0)
    (progn
      (setq prompt (getvar "LASTPROMPT"))
      (mcp:cancel-command)
      (mcp:fail (strcat "BricsCAD is still asking: " prompt))
    )
  )
  T
)

(defun mcp:plot-pdf (path layout paper landscape area window scale style-table)
  (mcp:keep-clean 'mcp:plot-pdf-now (list path layout paper landscape area window scale style-table))
)

;; The model and sheets ask different questions: see docs/phase-0-results.md.
(defun mcp:plot-pdf-now (path layout paper landscape area window scale style-table / model)
  (setq layout (mcp:layout-named (if layout layout (getvar "CTAB")))
        model (= (strcase layout) "MODEL"))
  (if (null area) (setq area (if model "extents" "layout")))
  (if (and model (= area "layout"))
    (mcp:fail "The model has no layout area to plot. Use extents or window.")
  )
  (if (null scale) (setq scale (if model "fit" "1:1")))
  (command "_.-PLOT")
  (mcp:answer-all
    (append
      (list "_Y" layout "Print As PDF.pc3" (if paper paper "") "_M"
            (cond ((null landscape) "") ((= landscape 1) "_L") (T "_P"))
            "_N")
      (cond
        ((= area "extents") (list "_E"))
        ((= area "layout") (list "_L"))
        (T (list "_W" (list (nth 0 window) (nth 1 window)) (list (nth 2 window) (nth 3 window))))
      )
      (list (if (= scale "fit") "_F" scale)
            (if (= area "layout") "" "_C")
            "_Y" (if style-table style-table "") "_Y")
      (if model (list "") (list "_N" "_Y" "_N"))
      (list path "_N" "_Y")
    )
  )
  layout
)

;; ---- Previews ----

;; Making a sheet current for the first time adds its viewports, and zooming changes the view.
;; Everything between the mark and _Back is undone, also on failure; the PNG stays.
(defun mcp:preview-image (path layout window)
  (mcp:keep-clean 'mcp:preview-image-now (list path layout window))
)

(defun mcp:preview-image-now (path layout window / result message)
  (if layout (setq layout (mcp:layout-named layout)))
  (command "_.UNDO" "_Mark")
  (setq *mcp-pending-error* nil
        result (vl-catch-all-apply 'mcp:preview-steps (list path layout window)))
  (if (vl-catch-all-error-p result)
    (setq message (cond (*mcp-pending-error*) ((vl-catch-all-error-message result))))
  )
  (mcp:cancel-command)
  (command "_.UNDO" "_Back")
  (if message
    (progn
      (setq *mcp-pending-error* message)
      (exit)
    )
  )
  T
)

(defun mcp:preview-steps (path layout window)
  (if layout (setvar "CTAB" layout))
  (if window
    (command "_.ZOOM" "_W" (list (nth 0 window) (nth 1 window)) (list (nth 2 window) (nth 3 window)))
    (command "_.ZOOM" "_E")
  )
  (command "_.PNGOUT" path)
  (if (> (getvar "CMDACTIVE") 0)
    (mcp:fail (strcat "BricsCAD did not finish the preview: " (getvar "LASTPROMPT")))
  )
)
