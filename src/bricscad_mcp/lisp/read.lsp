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

;; ---- Shared helpers ----

(defun mcp:fail (message)
  (setq *mcp-pending-error* message)
  (exit)
)

(defun mcp:page (items total limit offset)
  (mcp:obj
    (list
      (cons "items" (mcp:arr items))
      (cons "total" total)
      (cons "limit" limit)
      (cons "offset" offset)
    )
  )
)

(defun mcp:slice (items limit offset / out)
  (repeat offset (setq items (cdr items)))
  (while (and items (> limit 0))
    (setq out (cons (car items) out)
          items (cdr items)
          limit (1- limit))
  )
  (reverse out)
)

(defun mcp:selection-list (selection / index out)
  (if selection
    (progn
      (setq index (sslength selection))
      (while (> index 0)
        (setq index (1- index)
              out (cons (ssname selection index) out))
      )
    )
  )
  out
)

(defun mcp:selection-slice (selection limit offset / index last out)
  (if selection
    (progn
      (setq index offset
            last (min (sslength selection) (+ offset limit)))
      (while (< index last)
        (setq out (cons (ssname selection index) out)
              index (1+ index))
      )
    )
  )
  (reverse out)
)

(defun mcp:select (filter)
  (if filter (ssget "_X" filter) (ssget "_X"))
)

;; Makes a name safe as a selection filter, where # @ . * ? ~ [ ] - , ` are wildcards.
(defun mcp:wild-literal (text / out)
  (foreach code (vl-string->list text)
    (setq out
      (if (member code '(35 64 46 42 63 126 91 93 45 44 96))
        (cons code (cons 96 out))
        (cons code out)
      )
    )
  )
  (vl-list->string (reverse out))
)

(defun mcp:table-records (table / record out)
  (setq record (tblnext table T))
  (while record
    (setq out (cons record out)
          record (tblnext table))
  )
  (reverse out)
)

(defun mcp:group (code data) (cdr (assoc code data)))

(defun mcp:layout-of (data) (cond ((mcp:group 410 data)) ("Model")))

;; ---- Layers and layouts ----

(defun mcp:layer-item (record / name color flags)
  (setq name (mcp:group 2 record)
        color (mcp:group 62 record)
        flags (mcp:group 70 record))
  (mcp:obj
    (list
      (cons "name" name)
      (cons "on" (mcp:bool (>= color 0)))
      (cons "frozen" (mcp:bool (= (logand flags 1) 1)))
      (cons "locked" (mcp:bool (= (logand flags 4) 4)))
      (cons "color" (abs color))
      (cons "linetype" (mcp:group 6 record))
      (cons "entity_count"
            (mcp:count-selection (ssget "_X" (list (cons 8 (mcp:wild-literal name))))))
    )
  )
)

(defun mcp:list-layers (limit offset / records)
  (setq records (mcp:table-records "LAYER"))
  (mcp:page (mapcar 'mcp:layer-item (mcp:slice records limit offset)) (length records) limit offset)
)

(defun mcp:layout-item (name)
  (mcp:obj
    (list
      (cons "name" name)
      (cons "entity_count" (mcp:count-selection (ssget "_X" (list (cons 410 (mcp:wild-literal name))))))
      (cons "is_model" (mcp:bool (= name "Model")))
    )
  )
)

(defun mcp:list-layouts (limit offset / names)
  (setq names (cons "Model" (layoutlist)))
  (mcp:page (mapcar 'mcp:layout-item (mcp:slice names limit offset)) (length names) limit offset)
)

;; ---- Blocks and xrefs ----

(defun mcp:block-records (/ out)
  (foreach record (mcp:table-records "BLOCK")
    (if (not (wcmatch (strcase (mcp:group 2 record)) "`*MODEL_SPACE*,`*PAPER_SPACE*"))
      (setq out (cons record out))
    )
  )
  (reverse out)
)

(defun mcp:block-entities (record / entity out)
  (setq entity (mcp:group -2 record))
  (while entity
    (setq out (cons entity out)
          entity (entnext entity))
  )
  out
)

;; Counts how often each block is inserted inside other block definitions.
(defun mcp:nested-insert-counts (records / counts data name found)
  (foreach record records
    (foreach entity (mcp:block-entities record)
      (setq data (entget entity))
      (if (= (mcp:group 0 data) "INSERT")
        (progn
          (setq name (strcase (mcp:group 2 data))
                found (assoc name counts))
          (setq counts
            (if found
              (subst (cons name (1+ (cdr found))) found counts)
              (cons (cons name 1) counts)
            )
          )
        )
      )
    )
  )
  counts
)

(defun mcp:insert-count (name nested)
  (+ (mcp:count-selection
       (ssget "_X" (list '(0 . "INSERT") (cons 2 (mcp:wild-literal name)))))
     (cond ((cdr (assoc (strcase name) nested))) (0)))
)

(defun mcp:list-blocks (include-anonymous limit offset / all nested records flags)
  (setq all (mcp:block-records)
        nested (mcp:nested-insert-counts all))
  (foreach record all
    (setq flags (mcp:group 70 record))
    (if (or include-anonymous (= (logand flags 1) 0))
      (setq records (cons record records))
    )
  )
  (setq records (reverse records))
  (mcp:page
    (mapcar
      (function (lambda (record / name flags)
        (setq name (mcp:group 2 record)
              flags (mcp:group 70 record))
        (mcp:obj
          (list
            (cons "name" name)
            (cons "insert_count" (mcp:insert-count name nested))
            (cons "entity_count" (length (mcp:block-entities record)))
            (cons "is_xref" (mcp:bool (/= (logand flags 12) 0)))
            (cons "is_anonymous" (mcp:bool (= (logand flags 1) 1)))
          )
        )))
      (mcp:slice records limit offset))
    (length records) limit offset)
)

(defun mcp:xref-records (/ out)
  (foreach record (mcp:block-records)
    (if (/= (logand (mcp:group 70 record) 12) 0)
      (setq out (cons record out))
    )
  )
  (reverse out)
)

(defun mcp:xref-item (record / path)
  (setq path (mcp:group 1 record))
  (mcp:obj
    (list
      (cons "name" (mcp:group 2 record))
      (cons "path" path)
      (cons "resolved"
            (mcp:bool (and (= (logand (mcp:group 70 record) 32) 32) path (findfile path))))
    )
  )
)

(defun mcp:list-xrefs (limit offset / records)
  (setq records (mcp:xref-records))
  (mcp:page (mapcar 'mcp:xref-item (mcp:slice records limit offset)) (length records) limit offset)
)

;; ---- Entities ----

(defun mcp:entity-filter (types layer block layout / filter)
  (if types (setq filter (cons (cons 0 types) filter)))
  (if (and block (not types)) (setq filter (cons '(0 . "INSERT") filter)))
  (if layer (setq filter (cons (cons 8 layer) filter)))
  (if block (setq filter (cons (cons 2 block) filter)))
  (if layout (setq filter (cons (cons 410 layout) filter)))
  (reverse filter)
)

(defun mcp:bounding-box (entity / box)
  (setq box (vl-catch-all-apply 'vle-getboundingbox (list entity)))
  (if (vl-catch-all-error-p box) nil box)
)

(defun mcp:overlaps-p (box window)
  (and box
       (<= (car (car box)) (nth 2 window))
       (>= (car (cadr box)) (nth 0 window))
       (<= (cadr (car box)) (nth 3 window))
       (>= (cadr (cadr box)) (nth 1 window)))
)

(defun mcp:entity-item (entity / data)
  (setq data (entget entity))
  (mcp:obj
    (list
      (cons "handle" (mcp:group 5 data))
      (cons "type" (mcp:group 0 data))
      (cons "layer" (mcp:group 8 data))
      (cons "layout" (mcp:layout-of data))
      (cons "bbox" (mcp:bounding-box entity))
    )
  )
)

(defun mcp:query-entities (types layer block window layout limit offset / selection found)
  (setq selection (mcp:select (mcp:entity-filter types layer block layout)))
  (if window
    (progn
      (foreach entity (mcp:selection-list selection)
        (if (mcp:overlaps-p (mcp:bounding-box entity) window)
          (setq found (cons entity found))
        )
      )
      (setq found (reverse found))
      (mcp:page (mapcar 'mcp:entity-item (mcp:slice found limit offset)) (length found) limit offset)
    )
    (mcp:page
      (mapcar 'mcp:entity-item (mcp:selection-slice selection limit offset))
      (mcp:count-selection selection) limit offset)
  )
)

(defun mcp:get-entity (handle / entity data)
  (setq entity (vl-catch-all-apply 'handent (list handle)))
  (if (= (type entity) 'ENAME) (setq data (entget entity)))
  (if (null data) (mcp:fail (strcat "No entity has the handle " handle ".")))
  (mcp:obj
    (list
      (cons "handle" (mcp:group 5 data))
      (cons "type" (mcp:group 0 data))
      (cons "layer" (mcp:group 8 data))
      (cons "dxf" (mapcar (function (lambda (pair) (list (car pair) (cdr pair)))) data))
    )
  )
)

;; ---- Attributes and text ----

(defun mcp:insert-attributes (insert / entity data out)
  (setq entity (entnext insert) data (if entity (entget entity)))
  (while (and data (= (mcp:group 0 data) "ATTRIB"))
    (setq out (cons entity out)
          entity (entnext entity)
          data (if entity (entget entity)))
  )
  (reverse out)
)

(defun mcp:read-attributes (block layout limit offset / selection filter)
  (setq filter (list '(0 . "INSERT") '(66 . 1)))
  (if block (setq filter (append filter (list (cons 2 block)))))
  (if layout (setq filter (append filter (list (cons 410 layout)))))
  (setq selection (ssget "_X" filter))
  (mcp:page
    (mapcar
      (function (lambda (insert / data)
        (setq data (entget insert))
        (mcp:obj
          (list
            (cons "handle" (mcp:group 5 data))
            (cons "block" (mcp:group 2 data))
            (cons "layout" (mcp:layout-of data))
            (cons "attributes"
              (mcp:obj
                (mapcar
                  (function (lambda (attribute / values)
                    (setq values (entget attribute))
                    (cons (mcp:group 2 values) (mcp:group 1 values))))
                  (mcp:insert-attributes insert))))
          )
        )))
      (mcp:selection-slice selection limit offset))
    (mcp:count-selection selection) limit offset)
)

;; MTEXT longer than 250 characters is split across group 3 values before group 1.
(defun mcp:text-of (data / out)
  (foreach pair data
    (if (member (car pair) '(1 3)) (setq out (cons (cdr pair) out)))
  )
  (apply 'strcat (reverse out))
)

(defun mcp:text-matches-p (text query case-sensitive)
  (if case-sensitive
    (vl-string-search query text)
    (vl-string-search (strcase query) (strcase text))
  )
)

(defun mcp:text-item (data layout text)
  (mcp:obj
    (list
      (cons "handle" (mcp:group 5 data))
      (cons "type" (mcp:group 0 data))
      (cons "text" text)
      (cons "layer" (mcp:group 8 data))
      (cons "layout" layout)
      (cons "position" (mcp:group 10 data))
    )
  )
)

(defun mcp:find-text (query case-sensitive limit offset / found data text layout)
  (foreach entity (mcp:selection-list (ssget "_X" '((0 . "TEXT,MTEXT"))))
    (setq data (entget entity)
          text (mcp:text-of data))
    (if (mcp:text-matches-p text query case-sensitive)
      (setq found (cons (mcp:text-item data (mcp:layout-of data) text) found))
    )
  )
  (foreach insert (mcp:selection-list (ssget "_X" '((0 . "INSERT") (66 . 1))))
    (setq layout (mcp:layout-of (entget insert)))
    (foreach attribute (mcp:insert-attributes insert)
      (setq data (entget attribute)
            text (mcp:group 1 data))
      (if (mcp:text-matches-p text query case-sensitive)
        (setq found (cons (mcp:text-item data layout text) found))
      )
    )
  )
  (setq found (reverse found))
  (mcp:page (mcp:slice found limit offset) (length found) limit offset)
)
