;; The audit report. Relies on the helpers in read.lsp.

(defun mcp:audit-section (items sample-limit)
  (mcp:obj
    (list
      (cons "count" (length items))
      (cons "items" (mcp:arr (mcp:slice items sample-limit 0)))
    )
  )
)

(defun mcp:exempt-layer-p (name)
  (member (strcase name) '("0" "DEFPOINTS"))
)

;; Layers that hold entities inside block definitions, in upper case.
(defun mcp:layers-used-in-blocks (records / used layer)
  (foreach record records
    (foreach entity (mcp:block-entities record)
      (setq layer (strcase (mcp:group 8 (entget entity))))
      (if (not (member layer used)) (setq used (cons layer used)))
    )
  )
  used
)

(defun mcp:empty-layers (records / used out name)
  (setq used (mcp:layers-used-in-blocks records))
  (foreach layer (mcp:table-records "LAYER")
    (setq name (mcp:group 2 layer))
    (if (and (not (mcp:exempt-layer-p name))
             (not (member (strcase name) used))
             (null (ssget "_X" (list (cons 8 (mcp:wild-literal name))))))
      (setq out (cons name out))
    )
  )
  (reverse out)
)

(defun mcp:unused-blocks (records / nested out name flags)
  (setq nested (mcp:nested-insert-counts records))
  (foreach record records
    (setq name (mcp:group 2 record)
          flags (mcp:group 70 record))
    (if (and (= (logand flags 1) 0)
             (= (logand flags 12) 0)
             (= (mcp:insert-count name nested) 0))
      (setq out (cons name out))
    )
  )
  (reverse out)
)

(defun mcp:missing-xrefs (/ out path)
  (foreach record (mcp:xref-records)
    (setq path (mcp:group 1 record))
    (if (not (and path (findfile path)))
      (setq out (cons (mcp:xref-item record) out))
    )
  )
  (reverse out)
)

;; Point Z values and the elevation of 2D polylines. Returns nil when flat.
(defun mcp:elevation-of (data / found)
  (foreach pair data
    (cond
      ((and (= (car pair) 38) (numberp (cdr pair)) (> (abs (cdr pair)) 1e-9))
       (if (null found) (setq found (cdr pair))))
      ((and (member (car pair) '(10 11)) (= (type (cdr pair)) 'LIST) (= (length (cdr pair)) 3)
            (> (abs (caddr (cdr pair))) 1e-9))
       (if (null found) (setq found (caddr (cdr pair)))))
    )
  )
  found
)

(defun mcp:non-zero-elevation (/ out data elevation)
  (foreach entity (mcp:selection-list (ssget "_X"))
    (setq data (entget entity)
          elevation (mcp:elevation-of data))
    (if elevation
      (setq out
        (cons
          (mcp:obj
            (list
              (cons "handle" (mcp:group 5 data))
              (cons "type" (mcp:group 0 data))
              (cons "layer" (mcp:group 8 data))
              (cons "elevation" elevation)
            )
          )
          out))
    )
  )
  (reverse out)
)

(defun mcp:layer-allowed-p (name patterns / upper found)
  (setq upper (strcase name))
  (foreach pattern patterns
    (if (wcmatch upper (strcase pattern)) (setq found T))
  )
  found
)

(defun mcp:off-standard-layers (patterns / out name)
  (foreach layer (mcp:table-records "LAYER")
    (setq name (mcp:group 2 layer))
    (if (and (not (mcp:exempt-layer-p name)) (not (mcp:layer-allowed-p name patterns)))
      (setq out (cons name out))
    )
  )
  (reverse out)
)

(defun mcp:audit-report (patterns sample-limit / records)
  (setq records (mcp:block-records))
  (mcp:obj
    (list
      (cons "empty_layers" (mcp:audit-section (mcp:empty-layers records) sample-limit))
      (cons "unused_blocks" (mcp:audit-section (mcp:unused-blocks records) sample-limit))
      (cons "missing_xrefs" (mcp:audit-section (mcp:missing-xrefs) sample-limit))
      (cons "non_zero_elevation" (mcp:audit-section (mcp:non-zero-elevation) sample-limit))
      (cons "off_standard_layers"
            (if patterns (mcp:audit-section (mcp:off-standard-layers patterns) sample-limit)))
    )
  )
)
