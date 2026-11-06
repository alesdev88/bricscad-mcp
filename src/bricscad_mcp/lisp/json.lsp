;; JSON encoding for replies.
;; nil -> null, T -> true, strings and numbers as themselves, enames -> handle strings.
;; (mcp:obj pairs) -> object, (mcp:arr items) -> array, which may be empty.
;; Any other list -> array, and a dotted pair -> a two-item array.

(defun mcp:obj (pairs) (cons 'mcp:obj pairs))
(defun mcp:arr (items) (cons 'mcp:arr items))

(defun mcp:join (items separator / out)
  (foreach item items
    (setq out (if out (cons item (cons separator out)) (list item)))
  )
  (apply 'strcat (reverse out))
)

(defun mcp:hex-digit (n) (chr (if (< n 10) (+ 48 n) (+ 87 n))))

(defun mcp:json-string (text / out)
  (foreach code (vl-string->list text)
    (setq out
      (cond
        ((= code 34) (cons 34 (cons 92 out)))
        ((= code 92) (cons 92 (cons 92 out)))
        ((= code 10) (cons 110 (cons 92 out)))
        ((= code 13) (cons 114 (cons 92 out)))
        ((= code 9) (cons 116 (cons 92 out)))
        ((< code 32)
         (append (reverse (vl-string->list
                   (strcat "\\u00" (mcp:hex-digit (/ code 16)) (mcp:hex-digit (rem code 16)))))
                 out))
        (T (cons code out))
      )
    )
  )
  (strcat "\"" (vl-list->string (reverse out)) "\"")
)

(defun mcp:json-real (value / text)
  (setq text (rtos value 2 15))
  (cond
    ((or (vl-string-search "#" text) (wcmatch (strcase text) "*INF*,*NAN*")) "null")
    ((= (substr text 1 1) ".") (strcat "0" text))
    ((= (substr text 1 2) "-.") (strcat "-0" (substr text 2)))
    (T text)
  )
)

(defun mcp:json-list (value)
  (cond
    ((eq (car value) 'mcp:obj)
     (strcat "{"
       (mcp:join
         (mapcar
           (function (lambda (pair)
             (strcat (mcp:json-string (car pair)) ":" (mcp:json (cdr pair)))))
           (cdr value))
         ",")
       "}"))
    ((eq (car value) 'mcp:arr)
     (strcat "[" (mcp:join (mapcar 'mcp:json (cdr value)) ",") "]"))
    ((null (vl-list-length value))
     (strcat "[" (mcp:json (car value)) "," (mcp:json (cdr value)) "]"))
    (T (strcat "[" (mcp:join (mapcar 'mcp:json value) ",") "]"))
  )
)

(defun mcp:json (value / kind)
  (setq kind (type value))
  (cond
    ((null value) "null")
    ((eq value T) "true")
    ((eq value 'mcp:false) "false")
    ((= kind 'STR) (mcp:json-string value))
    ((= kind 'INT) (itoa value))
    ((= kind 'REAL) (mcp:json-real value))
    ((= kind 'LIST) (mcp:json-list value))
    ((= kind 'ENAME) (mcp:json-string (cdr (assoc 5 (entget value)))))
    (T (mcp:json-string (vl-prin1-to-string value)))
  )
)
