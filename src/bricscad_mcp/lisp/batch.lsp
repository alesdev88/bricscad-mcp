;; Batch jobs: one request per file. Relies on read.lsp, edit.lsp and export.lsp.

;; Opens the file read-only, runs one worker in it, and always closes it without saving.
;; A damaged file fails vla-open with E_FAIL and no dialog. Another drawing stays open, so
;; closing this one never stops the listener.
;; Any use of a document object after it has closed, even reading its name, ends BricsCAD.
;; The worker may close it, or rename it by saving, so whatever is new afterwards is closed.
(defun mcp:batch-file (path worker args / before document result message)
  (if (not (wcmatch worker "mcp:*")) (mcp:fail (strcat worker " is not a batch worker.")))
  (vlax-for open-document (mcp:documents) (setq before (cons open-document before)))
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
  (mcp:close-documents-not-in before)
  (if message
    (progn
      (setq *mcp-pending-error* message)
      (exit)
    )
  )
  result
)

;; Closes, without saving, every open document that is not in `keep`.
(defun mcp:close-documents-not-in (keep / extra)
  (vlax-for open-document (mcp:documents)
    (if (not (member open-document keep)) (setq extra (cons open-document extra)))
  )
  (foreach document extra (vl-catch-all-apply 'vla-close (list document :vlax-false)))
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

;; The client's code arrives as a string and is read as one form, so it cannot reach outside it.
;; Saving needs the batch's own drawing still current: code that closed it or switched away
;; would otherwise save another drawing, maybe the user's. Only system variables are read,
;; since a closed document's object must not be touched.
(defun mcp:batch-lisp (code source save-path / form value)
  (setq form (vl-catch-all-apply 'read (list (strcat "(progn\n" code "\n)"))))
  (if (vl-catch-all-error-p form)
    (mcp:fail (strcat "The LISP code could not be read: " (vl-catch-all-error-message form)))
  )
  (setq value (eval form))
  (if save-path
    (progn
      (if (not (and (mcp:current-path-p source)
                    (= (vla-get-readonly (mcp:active-document)) :vlax-true)))
        (mcp:fail "The LISP code left another drawing current, so nothing was saved.")
      )
      (mcp:save-copy save-path)
    )
  )
  value
)

(defun mcp:current-path-p (path)
  (= (strcase (vl-string-translate "\\" "/" (strcat (getvar "DWGPREFIX") (getvar "DWGNAME"))))
     (strcase (vl-string-translate "\\" "/" path)))
)
