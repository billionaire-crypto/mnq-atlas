"""Market-free primitives.

Spec §16.3: "core/ knows nothing about markets." Nothing in this subpackage may import
from `mnq_lab.spine`, `mnq_lab.conditioners`, `mnq_lab.outcomes`, or `mnq_lab.studies`,
and nothing here may name a contract, a session, or an exchange. Values such as tick size
arrive as parameters, never as constants defined here.
"""
