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
