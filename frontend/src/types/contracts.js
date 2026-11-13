/** @typedef {{id:number,name:string,source:string,rows:number,checksum:string,supersedes_id:?number,created_at:number}} Dataset */
/** @typedef {{fold:number,train_cutoff:string,train_days:number,window_start:string,window_end:string,mae:number,naive_mae:number,abs_error_sum:number,actual_sum:number,bias_sum:number,days:Array<BacktestDay>}} BacktestFold */
/** @typedef {{date:string,weekday:string,actual:number,forecast:number,naive:number,diff:number,naive_diff:number,abs_error:number,naive_abs_error:number}} BacktestDay */
/** @typedef {{folds:number,days:number,mae:number,naive_mae:number,wape:number,naive_wape:number,abs_error_sum:number,naive_abs_error_sum:number,actual_sum:number,bias_sum:number,rule:string}} BacktestAggregate */
/** @typedef {{record_count:number,date_start:string,date_end:string,checksum:string,alpha:number,horizon:number,safety_pct:number,note:string}} ResultSnapshot */
/** @typedef {{id:number,name:string,dataset_id:number,status:string,result:Object,approved:boolean,params:Object,error:string,created_at:number,finished_at:?number}} AnalysisJob */
/** @typedef {{id:number,name:string,job_id:number,destination:string,next_run:number,enabled:boolean}} ReportSchedule */
export {};
