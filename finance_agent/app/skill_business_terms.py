"""Finite Skill terminology data, never instructions, scope or authority."""


def validate_business_terms(value, fields):
    if type(value) is not list or len(value)>16:
        raise ValueError('业务术语必须是至多16项的结构化列表')
    result=[];seen=set()
    for entry in value:
        if type(entry) is not dict or set(entry)!={'term','object','metrics'}:
            raise ValueError('业务术语只接受term/object/metrics')
        term,obj,metrics=entry['term'],entry['object'],entry['metrics']
        if (type(term) is not str or not term.strip() or len(term)>80 or not term.isprintable()
                or type(obj) is not str or obj not in fields or (obj,term) in seen):
            raise ValueError('业务术语或对象无效或重复')
        if type(metrics) is not list or not 1<=len(metrics)<=8:
            raise ValueError('术语必须映射有限既有指标')
        output=[];mapped=set()
        for metric in metrics:
            if type(metric) is not dict or set(metric)!={'operation','field'}:
                raise ValueError('指标只接受operation/field')
            operation,field=metric['operation'],metric['field']
            if (type(operation) is not str or operation not in {'sum','count','details','min','max'}
                    or type(field) is not str or field not in set(fields[obj])|{'*'}
                    or (operation,field) in mapped):
                raise ValueError('术语指标必须是既有对象字段及指标，且不重复')
            mapped.add((operation,field));output.append({'operation':operation,'field':field})
        seen.add((obj,term));result.append({'term':term,'object':obj,'metrics':output})
    return result


def semantic_skill_terms(active_skills, fields):
    """Project Runtime-selected active configuration; no steps/tools or ACLs."""
    if type(active_skills) not in (list,tuple) or len(active_skills)>32:
        raise ValueError('共享能力定义超出有限输入')
    result=[]
    for skill in active_skills:
        if type(skill) is not dict:raise ValueError('共享能力定义结构无效')
        terms=validate_business_terms(skill.get('business_terms',[]),fields)
        if not terms:continue
        identifier,revision=skill.get('id'),skill.get('revision')
        if (type(identifier) is not str or not identifier.strip() or len(identifier)>100
                or type(revision) is not int or revision<1):
            raise ValueError('共享能力标识或版本无效')
        result.append({'skill_id':identifier,'revision':revision,'terms':terms})
    return result
