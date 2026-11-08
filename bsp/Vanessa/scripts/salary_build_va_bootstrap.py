"""Служебный запуск закрепленной Vanessa в серверной ИБ без изменения conf.cfg."""
from pathlib import Path
from lxml import etree as E
import uuid
import shutil
root=Path(__file__).resolve().parents[1]
source=root/'1c/extensions/УчетЗарплаты'
out=root/'1c/extensions/ИнструментыVanessaСервер'
M='http://v8.1c.ru/8.3/MDClasses';R='http://v8.1c.ru/8.3/xcf/readable';V='http://v8.1c.ru/8.1/data/core'
ns={'m':M,'r':R,'v':V}
def uid(n): return str(uuid.uuid5(uuid.NAMESPACE_URL,'server-vanessa-bootstrap/'+n))
t=E.parse(str(source/'Configuration.xml'));c=t.find('m:Configuration',ns)
c.set('uuid',uid('Configuration'))
for e in c.findall('.//r:ObjectId',ns):e.text=uid(e.text)
p=c.find('m:Properties',ns)
for name,value in [('Name','ИнструментыVanessaСервер'),('NamePrefix','ВА_'),('Version','1.0.0')]:
    e=p.find('m:'+name,ns)
    if e is not None:e.text=value
for n in p.findall('m:Synonym//v:content',ns):n.text='Служебный запуск Vanessa в серверной базе'
for name in ['DefaultRoles']:
    e=p.find('m:'+name,ns)
    if e is not None:e.clear();e.tag='{'+M+'}'+name
ch=c.find('m:ChildObjects',ns)
for e in list(ch):ch.remove(e)
E.SubElement(ch,'{'+M+'}CommonModule').text='ВА_ПодключениеСервер'
E.SubElement(ch,'{'+M+'}Language').text='Русский'
out.mkdir(parents=True,exist_ok=True)
(out/'Languages').mkdir(exist_ok=True)
lang=E.parse(str(source/'Languages/Русский.xml'))
lang.getroot()[0].set('uuid',uid('Language'))
lang.write(str(out/'Languages/Русский.xml'),encoding='UTF-8',xml_declaration=True)
t.write(str(out/'Configuration.xml'),encoding='UTF-8',xml_declaration=True)
t=E.parse(str(source/'CommonModules/ЗП_ЗарплатаСервер.xml'));obj=t.find('m:CommonModule',ns);obj.set('uuid',uid('Module'))
p=obj.find('m:Properties',ns);p.find('m:Name',ns).text='ВА_ПодключениеСервер'
p.find('m:ServerCall',ns).text='true'
for n in p.findall('m:Synonym//v:content',ns):n.text='Подключение закрепленной Vanessa'
(out/'CommonModules/ВА_ПодключениеСервер/Ext').mkdir(parents=True,exist_ok=True)
t.write(str(out/'CommonModules/ВА_ПодключениеСервер.xml'),encoding='UTF-8',xml_declaration=True)
epf=root/'1c/tmp/salary-audit-20261031/va-instrumented.epf'
(out/'CommonModules/ВА_ПодключениеСервер/Ext/Module.bsl').write_text('''Функция ПодключитьVanessa() Экспорт
	Защита = Новый ОписаниеЗащитыОтОпасныхДействий;
	Защита.ПредупреждатьОбОпасныхДействиях = Ложь;
	Данные = Новый ДвоичныеДанные("'''+str(epf)+'''");
	Адрес = ПоместитьВоВременноеХранилище(Данные);
	Возврат ВнешниеОбработки.Подключить(Адрес, , Ложь, Защита);
КонецФункции

Функция КешЗапускаVanessa(ПараметрЗапуска) Экспорт
	ПараметрыКоманды = Новый Структура;
	Для Каждого Часть Из СтрРазделить(ПараметрЗапуска, ";", Ложь) Цикл
		Разделитель = СтрНайти(Часть, "=");
		Если Разделитель > 0 Тогда ПараметрыКоманды.Вставить(Лев(Часть, Разделитель - 1), Сред(Часть, Разделитель + 1));
		Иначе ПараметрыКоманды.Вставить(Часть, Истина); КонецЕсли;
	КонецЦикла;
	НастройкиФайла = Новый Структура;
	Если ПараметрыКоманды.Свойство("VAParams") Тогда
		Чтение = Новый ЧтениеJSON; Чтение.ОткрытьФайл(ПараметрыКоманды.VAParams);
		НастройкиФайла = ПрочитатьJSON(Чтение); Чтение.Закрыть();
	КонецЕсли;
	Возврат Новый Структура("КешПрочитатьПеременныеСреды,КешПолучитьСтруктуруПараметров,КешVAParams", Новый Структура, ПараметрыКоманды, НастройкиФайла);
КонецФункции
''',encoding='utf-8-sig')
(out/'Ext').mkdir(exist_ok=True)
(out/'Ext/ManagedApplicationModule.bsl').write_text('''Перем ВА_Форма;

&После("ПриНачалеРаботыСистемы")
Процедура ВА_ПриНачалеРаботыСистемы()
	Если СтрНайти(ПараметрЗапуска, "VANESSA_SERVER_BOOTSTRAP") = 0 Тогда Возврат; КонецЕсли;
	ПодключитьОбработчикОжидания("ВА_ЗапуститьVanessa", 2, Истина);
КонецПроцедуры

Процедура ВА_ЗапуститьVanessa() Экспорт
	ВА_Этап("01", "Начало запуска закрепленной Vanessa");
	Попытка
		ВА_Этап("02", "Подключение обработки на сервере");
		Имя = ВА_ПодключениеСервер.ПодключитьVanessa();
		ВА_Этап("03", "Подключена обработка: " + Имя);
		ПараметрыФормыВА = Новый Структура("ИнициализироватьVanessaEditor,ЭтоLinuxКлиент,ПараметрЗапуска,КаталогИнструментов,КаталогПроекта", Ложь, Ложь, ПараметрЗапуска,
			"C:\\Users\\IT\\Desktop\\hakaton\\1c\\v8runner\\vanessa\\epf\\1.2.043.42", "C:\\Users\\IT\\Desktop\\hakaton");
		ПараметрыФормыВА.Вставить("КешПараметровЗапуска", ВА_ПодключениеСервер.КешЗапускаVanessa(ПараметрЗапуска));
		ВА_Этап("04", "Получение управляемой формы");
		ВА_Форма = ПолучитьФорму("ВнешняяОбработка." + Имя + ".Форма.УправляемаяФорма", ПараметрыФормыВА);
		ВА_Этап("05", "Управляемая форма получена");
		ВА_Форма.Объект.ИспользоватьКомпонентуVanessaExt = Истина;
		ВА_Форма.Объект.ИспользоватьРедакторVanessaEditor = Ложь;
		ВА_Форма.Объект.КаталогФич = "C:\\Users\\IT\\Desktop\\hakaton\\1c\\vanessa\\features\\salary-audit-forms.feature";
		ВА_Форма.Объект.ЗагрузкаФичПриОткрытии = "Не загружать";
		Попытка
			ВА_МодульMCP = ПолучитьФорму("ВнешняяОбработка." + Имя + ".Форма.MCPVA", , ВА_Форма);
			ВА_Этап("05a", "Форма MCPVA получена");
			ВА_МодульMCP.ИнициализацияФормы(ВА_Форма);
			ВА_Этап("05b", "Форма MCPVA инициализирована");
			ВА_МодульMCP.ЗарегистрироватьИнструментыMCP();
			ВА_Этап("05c", "Команды MCP зарегистрированы до открытия формы");
		Исключение
			ВА_Этап("05error", ПодробноеПредставлениеОшибки(ИнформацияОбОшибке()));
		КонецПопытки;
		ПодключитьОбработчикОжидания("ВА_ПроверитьРегистрацию", 15, Истина);
		ВА_Форма.Открыть();
		ВА_Этап("06", "Открытие формы выполнено");
	Исключение
		ВА_Этап("error", ПодробноеПредставлениеОшибки(ИнформацияОбОшибке()));
	КонецПопытки;
КонецПроцедуры

Процедура ВА_Этап(Номер, Текст)
	ДокументЛога = Новый ТекстовыйДокумент; ДокументЛога.УстановитьТекст(Текст);
	ДокументЛога.Записать("C:\\Users\\IT\\Desktop\\hakaton\\1c\\logs\\va-bootstrap-" + Номер + ".log", КодировкаТекста.UTF8);
КонецПроцедуры

&Перед("ОбработкаВнешнегоСобытия")
Процедура ВА_ДоВнешнегоСобытия(Источник, Событие, Данные)
	Если СтрНайти(ПараметрЗапуска, "VANESSA_SERVER_BOOTSTRAP") = 0 Тогда Возврат; КонецЕсли;
	ВА_Этап("event-before", Источник + " / " + Событие + " / " + Строка(ТипЗнч(Данные)) + " / " + ?(ТипЗнч(Данные) = Тип("Строка"), Строка(СтрДлина(Данные)), ""));
КонецПроцедуры

&После("ОбработкаВнешнегоСобытия")
Процедура ВА_ПослеВнешнегоСобытия(Источник, Событие, Данные)
	Если СтрНайти(ПараметрЗапуска, "VANESSA_SERVER_BOOTSTRAP") = 0 Тогда Возврат; КонецЕсли;
	ВА_Этап("event-after", Источник + " / " + Событие + " / " + Строка(ТипЗнч(Данные)) + " / " + ?(ТипЗнч(Данные) = Тип("Строка"), Строка(СтрДлина(Данные)), ""));
КонецПроцедуры

Асинх Процедура ВА_ПроверитьРегистрацию() Экспорт
	Журнал = Новый ЗаписьТекста("C:\\Users\\IT\\Desktop\\hakaton\\1c\\logs\\va-bootstrap-state.log", КодировкаТекста.UTF8);
	Попытка
		Журнал.ЗаписатьСтроку("Инициализация формы: " + Строка(ВА_Форма.СработалиВсеАсинхронныеОбработчикиФормыПриОткрытии));
		Журнал.ЗаписатьСтроку("Версия поставки: " + ВА_Форма.Объект.ВерсияПоставки);
		МодульВА = ВА_Форма.МодульMCPVA();
		МодульВА.ЗарегистрироватьИнструментыMCP();
		Журнал.ЗаписатьСтроку("Регистрация команд Vanessa выполнена");
		ВА_Реестр = Вычислить("Мсп_РеестрКлиент");
		Журнал.ЗаписатьСтроку("Команд в клиентском реестре: " + ВА_Реестр.РеестрИнструментов().Количество());
		Журнал.Закрыть();
		ВА_Транспорт = Вычислить("Мсп_ТранспортРеестрыКлиент");
		Ждать ВА_Транспорт.СинхронизироватьРеестрыСКомпонентой();
		ВА_Этап("sync", "Синхронизация реестра с транспортом выполнена");
	Исключение
		ВА_Этап("state-error", ПодробноеПредставлениеОшибки(ИнформацияОбОшибке()));
	КонецПопытки;
КонецПроцедуры
''',encoding='utf-8-sig')
# Загрузка фич через штатное дерево без зависимости от HTML-редактора.
app_path=out/'Ext/ManagedApplicationModule.bsl'
app_code=app_path.read_text(encoding='utf-8-sig')
app_code=app_code.replace('ВА_Этап("06", "Открытие формы выполнено");', 'ВА_Этап("06", "Открытие формы выполнено");\n\t\tПодключитьОбработчикОжидания("ВА_ОбработатьКомандуЗагрузки", 1);',1)
app_code+='\n'+(root/'scripts/salary_va_native_loader.bsl').read_text(encoding='utf-8-sig')
app_path.write_text(app_code,encoding='utf-8-sig')

D='http://v8.1c.ru/8.3/xcf/dumpinfo'
d=E.Element('{'+D+'}ConfigDumpInfo',nsmap={None:D},format='Hierarchical',version='2.20');cv=E.SubElement(d,'{'+D+'}ConfigVersions')
for name,id_ in [('Configuration.ИнструментыVanessaСервер',uid('Configuration')),('CommonModule.ВА_ПодключениеСервер',uid('Module'))]:
    E.SubElement(cv,'{'+D+'}Metadata',name=name,id=id_,configVersion='0'*40)
E.ElementTree(d).write(str(out/'ConfigDumpInfo.xml'),encoding='UTF-8',xml_declaration=True)
print(out)
