;; Batch jobs: one request per file. Relies on read.lsp, edit.lsp and export.lsp.

;; Opens the file read-only, runs one worker in it, and always closes it without saving.
;; A damaged file fails vla-open with E_FAIL and no dialog. Another drawing stays open, so
;; closing this one never stops the listener.
(defun mcp:batch-file (path worker args / document result message)
  (if (not (wcmatch worker "mcp:*")) (mcp:fail (strcat worker " is not a batch worker.")))
  (setq document (vl-catch-all-apply 'vla-open (list (mcp:documents) path :vlax-true)))
  (if (vl-catch-all-error-p document)
    (mcp:fail (strcat "BricsCAD could not open " path ": " (vl-catch-all-error-message document)))
  )
  (setq *mcp-pending-error* nil
        result (vl-catch-all-apply (read worker) args))
  (if (vl-catch-all-error-p result)
    (setq message (cond (*mcp-pending-error*) ((vl-catch-all-error-message result))))
  )
  (mcp:cancel-command)
  (vl-catch-all-apply 'vla-close (list document :vlax-false))
  (if message
    (progn
      (setq *mcp-pending-error* message)
      (exit)
    )
  )
  result
)

;; ---- Workers that write. Each writes to a temporary path that Python then moves. ----

(defun mcp:save-copy (path)
  (command "_.SAVEAS" "" path)
  (if (or (> (getvar "CMDACTIVE") 0) (not (findfile path)))
    (progn
      (mcp:cancel-command)
      (mcp:fail (strcat "BricsCAD did not save " path "."))
    )
  )
  T
)

;; Plots every sheet to <folder>/<n>.pdf, n from 1, and returns the sheet names in that order.
(defun mcp:plot-sheets (folder paper landscape area window scale style-table / n names)
  (if (null (layoutlist)) (mcp:fail "This drawing has no sheets."))
  (setq n 0)
  (foreach name (layoutlist)
    (setq n (1+ n))
    (mcp:plot-pdf-now (strcat folder "/" (itoa n) ".pdf") name paper landscape area window scale style-table)
    (setq names (cons name names))
  )
  (reverse names)
)
