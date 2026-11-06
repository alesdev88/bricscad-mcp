;; Reading drawings. Results are plain values that json.lsp can encode.

(defun mcp:bool (value)
  (if (or (null value) (= value :vlax-false)) 'mcp:false T)
)

(defun mcp:active-modified-p ()
  (= (vla-get-saved (mcp:active-document)) :vlax-false)
)

(defun mcp:count-selection (selection)
  (if selection (sslength selection) 0)
)

(defun mcp:drawing-info (/ document)
  (setq document (mcp:active-document))
  (mcp:obj
    (list
      (cons "name" (getvar "DWGNAME"))
      (cons "path" (strcat (getvar "DWGPREFIX") (getvar "DWGNAME")))
      (cons "read_only" (mcp:bool (vla-get-readonly document)))
      (cons "modified" (mcp:bool (mcp:active-modified-p)))
      (cons "units" (getvar "INSUNITS"))
      (cons "limits" (list (getvar "LIMMIN") (getvar "LIMMAX")))
      (cons "extents" (list (getvar "EXTMIN") (getvar "EXTMAX")))
      (cons "entity_count" (mcp:count-selection (ssget "_X")))
      (cons "layouts" (cons "Model" (layoutlist)))
    )
  )
)

(defun mcp:open-drawing (path read-only)
  (vla-open (mcp:documents) path (if read-only :vlax-true :vlax-false))
  (mcp:drawing-info)
)

;; The listener stops if the only document closes, so a blank one takes its place.
;; vla-close never prompts. Unlike _.CLOSE it cannot save by accident.
(defun mcp:close-drawing (/ document)
  (setq document (mcp:active-document))
  (if (= (vla-get-count (mcp:documents)) 1) (vla-add (mcp:documents)))
  (vla-close document :vlax-false)
  (getvar "DWGNAME")
)
