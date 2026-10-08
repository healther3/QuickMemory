// @vitest-environment jsdom
import React from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import Settings from '../src/pages/Settings';
import Editor from '../src/pages/Editor';
import ExamPage from '../src/pages/Exam';
import ImportPage from '../src/pages/Import';
import AnswerPanel from '../src/AnswerPanel';
import type { Answer, Exam } from '../src/api';

const config = {provider:'deepseek',base_url:'https://api.deepseek.com/v1',model:'deepseek-chat',has_api_key:false,
  judge_count:3,judge_temperature:0.7,merge_temperature:0.2,w_accuracy:0.5,w_completeness:0.5,pass_threshold:60,
  json_mode:'auto',request_timeout:60};
const folders = [{id:1,name:'测试文件夹',card_count:1,created_at:'2026-10-07T10:00:00Z'},
  {id:2,name:'另一个文件夹',card_count:0,created_at:'2026-10-07T10:00:00Z'}];
const labels = [{id:1,name:'遗漏要点'},{id:2,name:'概念混淆'}];
const calls: {path:string;method:string;body:any}[] = [];
let handler: (path:string, method:string, body:any) => any;

beforeEach(() => {
  calls.length=0;
  localStorage.clear();
  vi.stubGlobal('confirm', vi.fn(() => true));
  handler = (path, method, body) => {
    if(path==='/api/settings') return method==='PUT'?{...config,...body,api_key:undefined,has_api_key:!!body.api_key}:config;
    if(path==='/api/providers') return [{id:'deepseek',name:'DeepSeek',base_url:config.base_url,suggested_model:config.model}];
    if(path==='/api/local-service') return {port:8000,page_port:8000,can_stop:true,preferred_port:8000};
    if(path==='/api/error-types') return method==='POST'?{id:3,name:body.name}:labels;
    if(path==='/api/folders') return folders;
    if(path==='/api/tags') return [];
    throw new Error(`测试未定义的接口 ${method} ${path}`);
  };
  vi.stubGlobal('fetch', vi.fn(async (url: RequestInfo | URL, init?:RequestInit) => {
    const path=String(url), method=init?.method||'GET';
    const body=typeof init?.body==='string'?JSON.parse(init.body):undefined;
    calls.push({path,method,body});
    const value=await handler(path,method,body);
    return new Response(JSON.stringify(value), {status:200,headers:{'Content-Type':'application/json'}});
  }));
});
afterEach(() => {cleanup();vi.unstubAllGlobals();});

function route(element: React.ReactNode, path='/') {
  return render(<MemoryRouter initialEntries={[path]}>{element}</MemoryRouter>);
}

describe('设置与卡片编辑', () => {
  it('网页端口独立保存并在再次进入时恢复，当前地址保持不变', async () => {
    let service={port:8000,page_port:8000,can_stop:true,preferred_port:8000};
    const previous=handler;
    handler=(path,method,body)=>{
      if(path==='/api/local-service') {
        if(method==='PUT') service={...service,...body};
        return service;
      }
      return previous(path,method,body);
    };
    const first=route(<Settings/>);
    const port=await screen.findByRole('spinbutton',{name:'下次启动端口'});
    await userEvent.clear(port);
    await userEvent.type(port,'8080');
    await userEvent.click(screen.getByRole('button',{name:'保存端口'}));
    await screen.findByText(/首选端口 8080 已保存/);
    expect(screen.getByRole('link',{name:'http://localhost:8000'}).getAttribute('href')).toBe('http://localhost:8000');
    expect(calls.find(c=>c.path==='/api/local-service'&&c.method==='PUT')?.body).toEqual({preferred_port:8080});
    expect(calls.filter(c=>c.path==='/api/settings'&&c.method==='PUT')).toHaveLength(0);
    expect(calls.filter(c=>c.path==='/api/local-service/stop')).toHaveLength(0);
    first.unmount();
    route(<Settings/>);
    expect((await screen.findByRole('spinbutton',{name:'下次启动端口'}) as HTMLInputElement).value).toBe('8080');
    await screen.findByText('下次启动将优先使用端口 8080。');
  });

  it('关闭本地服务须确认，成功后保留重新启动提示', async () => {
    const previous=handler;
    handler=(path,method,body)=>path==='/api/local-service/stop'?{stopping:true}:previous(path,method,body);
    vi.mocked(window.confirm).mockReturnValueOnce(false).mockReturnValueOnce(true);
    route(<Settings/>);
    const close=await screen.findByRole('button',{name:'关闭本地服务'});
    await userEvent.click(close);
    expect(calls.filter(c=>c.path==='/api/local-service/stop')).toHaveLength(0);
    await userEvent.click(close);
    await screen.findByText('已请求关闭本地服务');
    expect(screen.getByText(/需要使用时，再次双击/)).toBeTruthy();
    expect(calls.filter(c=>c.path==='/api/local-service/stop'&&c.method==='POST')).toHaveLength(1);
    expect(screen.queryByRole('button',{name:'关闭本地服务'})).toBeNull();
    expect(screen.queryByText('服务已关闭')).toBeNull();
  });

  it('端口保存和关闭失败保留输入与重试操作', async () => {
    const previous=handler;
    let stops=0;
    handler=(path,method,body)=>{
      if(path==='/api/local-service'&&method==='PUT') throw new TypeError('模拟保存失败');
      if(path==='/api/local-service/stop') {
        if(++stops===1) throw new TypeError('模拟关闭失败');
        return {stopping:true};
      }
      return previous(path,method,body);
    };
    route(<Settings/>);
    const port=await screen.findByRole('spinbutton',{name:'下次启动端口'});
    await userEvent.clear(port);
    await userEvent.type(port,'8081');
    await userEvent.click(screen.getByRole('button',{name:'保存端口'}));
    await screen.findByRole('alert');
    expect((port as HTMLInputElement).value).toBe('8081');
    expect((screen.getByRole('button',{name:'保存端口'}) as HTMLButtonElement).disabled).toBe(false);
    await userEvent.click(screen.getByRole('button',{name:'关闭本地服务'}));
    await screen.findByRole('alert');
    expect(screen.queryByText('已请求关闭本地服务')).toBeNull();
    await userEvent.click(screen.getByRole('button',{name:'关闭本地服务'}));
    await screen.findByText('已请求关闭本地服务');
    expect(stops).toBe(2);
  });

  it('服务信息失败不阻断模型设置，重试后展示不支持网页关闭的原因', async () => {
    const previous=handler;
    let reads=0;
    handler=(path,method,body)=>{
      if(path==='/api/local-service') {
        if(++reads===1) throw new TypeError('模拟状态读取失败');
        return {port:8000,page_port:5173,can_stop:false,preferred_port:8000};
      }
      return previous(path,method,body);
    };
    route(<Settings/>);
    await screen.findByRole('alert');
    expect(await screen.findByPlaceholderText('输入 API 密钥')).toBeTruthy();
    expect((screen.getByRole('button',{name:'保存设置'}) as HTMLButtonElement).disabled).toBe(false);
    await userEvent.click(screen.getByRole('button',{name:'重试'}));
    const close=await screen.findByRole('button',{name:'关闭本地服务'});
    expect((close as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText(/当前启动方式不支持从网页关闭/)).toBeTruthy();
    expect(screen.getByRole('link',{name:'http://localhost:5173'}).getAttribute('href')).toBe('http://localhost:5173');
  });

  it('错误类型操作不会提交模型设置，也不存在嵌套表单', async () => {
    route(<Settings/>);
    const name=await screen.findByRole('textbox',{name:'新增名称'});
    expect(document.querySelector('form form')).toBeNull();
    await userEvent.type(name,'测试新类型');
    await userEvent.click(screen.getByRole('button',{name:'添加'}));
    await waitFor(()=>expect(calls.filter(c=>c.path==='/api/error-types'&&c.method==='POST')).toHaveLength(1));
    expect(calls.filter(c=>c.path==='/api/settings'&&c.method==='PUT')).toHaveLength(0);
  });

  it('输入密钥默认遮挡；测试连接不会保存设置', async () => {
    const previous=handler;
    handler=(path,method,body)=>path==='/api/settings/test'?{ok:true,message:'模拟连接成功'}:previous(path,method,body);
    route(<Settings/>);
    const input=await screen.findByPlaceholderText('输入 API 密钥');
    expect(input.getAttribute('type')).toBe('password');
    await userEvent.type(input,'non-real-test-key');
    await userEvent.click(screen.getByRole('button',{name:'测试连接'}));
    await screen.findByText(/模拟连接成功/);
    expect(calls.find(c=>c.path==='/api/settings/test')?.body.api_key).toBe('non-real-test-key');
    expect(calls.filter(c=>c.path==='/api/settings'&&c.method==='PUT')).toHaveLength(0);
  });

  it('核对只发送编辑内容，必须明确采用建议并保存卡片', async () => {
    const previous=handler;
    handler=(path,method,body)=>{
      if(path==='/api/precheck') return {correct_parts:['核对正确'],wrong_parts:[],uncertain_parts:[],clarifying_questions:[],suggested_rewrite:'建议的新定义'};
      if(path==='/api/cards'&&method==='POST') return {id:4,...body,tags:[],folders:[],created_at:'2026-10-07',updated_at:'2026-10-07'};
      return previous(path,method,body);
    };
    route(<Routes><Route path='/cards/new' element={<Editor/>}/><Route path='/cards/:id/edit' element={<p>保存后页面</p>}/></Routes>, '/cards/new');
    await screen.findByLabelText('测试文件夹');
    await userEvent.type(screen.getByLabelText(/术语/),'测试术语');
    const definition=screen.getByLabelText(/参考定义/);
    await userEvent.type(definition,'我原来的定义');
    await userEvent.click(screen.getByRole('button',{name:'AI 核对定义'}));
    await screen.findByText('建议的新定义');
    expect((definition as HTMLTextAreaElement).value).toBe('我原来的定义');
    expect(calls.filter(c=>c.method==='POST'&&c.path==='/api/cards')).toHaveLength(0);
    await userEvent.click(screen.getByRole('button',{name:'采用建议改写'}));
    expect((definition as HTMLTextAreaElement).value).toBe('建议的新定义');
    await userEvent.click(screen.getByLabelText('测试文件夹'));
    await userEvent.click(screen.getByLabelText('另一个文件夹'));
    await userEvent.click(screen.getByRole('button',{name:'保存卡片'}));
    await screen.findByText('保存后页面');
    expect(calls.find(c=>c.method==='POST'&&c.path==='/api/cards')?.body.folder_ids).toEqual([1,2]);
    expect(calls.find(c=>c.method==='POST'&&c.path==='/api/cards')?.body.definition).toBe('建议的新定义');
  });
});

describe('考试和结果', () => {
  const question={id:9,card_id:2,position:0,term:'测试术语',user_answer:'',time_spent_ms:0,submitted_at:null,status:'pending' as const};
  const exam:Exam={id:1,folder_id:1,folder_name:'测试文件夹',parent_session_id:null,started_at:'2026-10-07',finished_at:null,total:1,submitted_count:0,graded_count:0,failed_count:0,pass_threshold:60,answers:[question]};

  it('提交结果不确定时重试使用相同答案和耗时，成功后立即进入结果页', async () => {
    let submissions=0;
    const previous=handler;
    handler=(path,method,body)=>{
      if(path==='/api/exams/1') return exam;
      if(path==='/api/answers/9/submit') {
        submissions++;
        if(submissions===1) throw new TypeError('模拟响应丢失');
        return {accepted:true,answer_id:9};
      }
      return previous(path,method,body);
    };
    route(<Routes><Route path='/exams/:id' element={<ExamPage/>}/><Route path='/exams/:id/results' element={<p>已进入结果页</p>}/></Routes>, '/exams/1');
    await userEvent.type(await screen.findByLabelText('你的回答'),'测试回答');
    await userEvent.click(screen.getByRole('button',{name:/提交/}));
    await screen.findByRole('alert');
    await userEvent.click(screen.getByRole('button',{name:/提交/}));
    await screen.findByText('已进入结果页');
    const bodies=calls.filter(c=>c.path==='/api/answers/9/submit').map(c=>c.body);
    expect(bodies).toHaveLength(2);
    expect(bodies[0]).toEqual(bodies[1]);
    expect(localStorage.getItem('qm-answer-9')).toBeNull();
  });

  const answer:Answer={...question,status:'graded',submitted_at:'2026-10-07T11:00:00Z',definition:'参考原文',user_answer:'回答原文',
    accuracy:70,completeness:50,final_score:60,merged_feedback:{correct_parts:['正确片段'],wrong_parts:[],uncertain_parts:[],error_types:['遗漏要点']},
    model_knowledge_notes:['这段只是模型提示'],judges:[],disagreement:false,merge_fallback:false,grading_error:null,prompt_version:'test',model_name:'test',created_at:'2026-10-07T10:00:00Z',error_types:[labels[0]]};

  it('结果轮询刷新不会清空正在编辑的错误标签', async () => {
    const rendered=render(<AnswerPanel answer={answer} types={labels} onUpdate={()=>{}} defaultOpen/>);
    await userEvent.click(screen.getByRole('button',{name:'修改标签'}));
    await userEvent.click(screen.getByLabelText('概念混淆'));
    expect((screen.getByLabelText('概念混淆') as HTMLInputElement).checked).toBe(true);
    rendered.rerender(<AnswerPanel answer={{...answer,error_types:[{...labels[0]}]}} types={labels} onUpdate={()=>{}} defaultOpen/>);
    expect((screen.getByLabelText('概念混淆') as HTMLInputElement).checked).toBe(true);
    expect(screen.getByRole('heading',{name:'模型提示（不计分，仅供参考）'})).toBeTruthy();
  });

  it('评分失败时不展示伪造分数或肯定的计分反馈', () => {
    render(<AnswerPanel answer={{...answer,status:'failed',accuracy:null,completeness:null,final_score:null,merged_feedback:{} as any,error_types:[],model_knowledge_notes:[]}} types={labels} onUpdate={()=>{}} defaultOpen/>);
    expect(screen.queryByRole('heading',{name:'正确的部分'})).toBeNull();
    expect(screen.getAllByText('未评分').length).toBeGreaterThan(0);
    expect(screen.getByRole('button',{name:'重新评分'})).toBeTruthy();
  });
});

it('导入必须先预览再确认，使用同一令牌并保留报告', async () => {
  const previous=handler;
  const report={added:1,skipped:0,overwritten:0,invalid:0,preview_token:'preview-test-token',rows:[{term:'导入术语',definition:'定义',action:'add',reason:'新增卡片'}]};
  handler=(path,method,body)=>{
    if(path==='/api/imports/preview') return report;
    if(path==='/api/imports/confirm') return {...report,folder_id:4};
    return previous(path,method,body);
  };
  route(<ImportPage/>);
  await userEvent.type(screen.getByLabelText('新文件夹名称'),'新题库');
  fireEvent.change(screen.getByLabelText('或粘贴 JSON 内容'),{target:{value:'{"导入术语":"定义"}'}});
  await userEvent.click(screen.getByRole('button',{name:'生成导入预览'}));
  await screen.findByRole('heading',{name:'导入预览'});
  expect(calls.filter(c=>c.path==='/api/imports/confirm')).toHaveLength(0);
  await userEvent.click(screen.getByRole('button',{name:'确认导入'}));
  await screen.findByRole('heading',{name:'导入报告'});
  expect(calls.find(c=>c.path==='/api/imports/confirm')?.body.preview_token).toBe('preview-test-token');
  expect(screen.getByRole('link',{name:'查看已导入卡片'}).getAttribute('href')).toBe('/cards?folder_id=4');
});
