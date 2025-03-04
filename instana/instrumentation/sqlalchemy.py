# (c) Copyright IBM Corp. 2021
# (c) Copyright Instana Inc. 2018

from __future__ import absolute_import

import re
from operator import attrgetter

from ..log import logger
from ..util.traceutils import get_active_tracer

try:
    import sqlalchemy
    from sqlalchemy import event
    from sqlalchemy.engine import Engine

    url_regexp = re.compile(r"\/\/(\S+@)")


    @event.listens_for(Engine, 'before_cursor_execute', named=True)
    def receive_before_cursor_execute(**kw):
        try:
            active_tracer = get_active_tracer()

            # If we're not tracing, just return
            if active_tracer is None:
                return

            scope = active_tracer.start_active_span("sqlalchemy", child_of=active_tracer.active_span)
            context = kw['context']
            if context:
                context._stan_scope = scope

            conn = kw['conn']
            url = str(conn.engine.url)
            scope.span.set_tag('sqlalchemy.sql', kw['statement'])
            scope.span.set_tag('sqlalchemy.eng', conn.engine.name)
            scope.span.set_tag('sqlalchemy.url', url_regexp.sub('//', url))
        except Exception as e:
            logger.debug(e)
        return


    @event.listens_for(Engine, 'after_cursor_execute', named=True)
    def receive_after_cursor_execute(**kw):
        context = kw['context']

        if context is not None and hasattr(context, '_stan_scope'):
            scope = context._stan_scope
            if scope is not None:
                scope.close()


    error_event = "handle_error"
    # Handle dbapi_error event; deprecated since version 0.9
    if sqlalchemy.__version__[0] == "0":
        error_event = "dbapi_error"


    def _set_error_tags(context, exception_string, scope_string):
        scope, context_exception = None, None
        if attrgetter(scope_string)(context) and attrgetter(exception_string)(context):
            scope = attrgetter(scope_string)(context)
            context_exception = attrgetter(exception_string)(context)
        if scope and context_exception:
            scope.span.log_exception(context_exception)
            scope.close()
        else:
            scope.span.log_exception("No %s specified." % error_event)
            scope.close()


    @event.listens_for(Engine, error_event, named=True)
    def receive_handle_db_error(**kw):

        if get_active_tracer() is None:
            return

        # support older db error event
        if error_event == "dbapi_error":
            context = kw.get('context')
            exception_string = 'exception'
            scope_string = '_stan_scope'
        else:
            context = kw.get('exception_context')
            exception_string = 'sqlalchemy_exception'
            scope_string = 'execution_context._stan_scope'

        if context:
            _set_error_tags(context, exception_string, scope_string)


    logger.debug("Instrumenting sqlalchemy")

except ImportError:
    pass
